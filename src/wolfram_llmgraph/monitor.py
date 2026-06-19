"""Runtime observability for the LLMGraph engine.

Mirrors the state Wolfram surfaces while evaluating an ``LLMGraph`` — the
"Computing nodes / Elapsed time" progress panel and the per-node dependency
state (``PendingDependencies``) — but as a structured, streamable event feed an
external runtime and a web UI can consume.

A :class:`RunMonitor` is attached to an :class:`~wolfram_llmgraph.LLMGraph`. As
the graph runs, each node transitions through:

    pending -> running -> done | canceled | skipped | error

The monitor keeps a live snapshot (per-node status + timing + value preview +
optional token usage) and pushes each transition to any subscribers (e.g. an
SSE handler), so the front end lights up nodes as they execute.

No third-party dependencies — stdlib only, thread-safe.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from queue import Queue
from typing import Any

PENDING = "pending"
RUNNING = "running"
DONE = "done"
CANCELED = "canceled"
SKIPPED = "skipped"
ERROR = "error"

_MAX_PREVIEW = 280


def _preview(value: Any) -> str:
    s = str(value)
    s = s.replace("\r\n", "\n")
    if len(s) > _MAX_PREVIEW:
        s = s[:_MAX_PREVIEW] + "…"
    return s


@dataclass
class NodeRecord:
    name: str
    kind: str
    deps: list[str] = field(default_factory=list)
    status: str = PENDING
    started: float | None = None   # epoch seconds
    ended: float | None = None
    duration: float | None = None  # seconds
    preview: str | None = None
    error: str | None = None
    usage: dict | None = None      # token usage, when the backend reports it
    model: str | None = None       # model used for LLM nodes
    _full_value: Any = field(default=None, repr=False)  # 完整输出值


@dataclass
class RunState:
    run_id: str
    graph: dict                     # static structure (nodes/edges/inputs/outputs/kinds)
    inputs: dict
    nodes: dict[str, NodeRecord]
    started: float
    ended: float | None = None
    status: str = RUNNING           # running | done | error

    def progress(self) -> tuple[int, int]:
        done = sum(
            1 for n in self.nodes.values()
            if n.status in (DONE, CANCELED, SKIPPED, ERROR)
        )
        return done, len(self.nodes)


class RunMonitor:
    """Collects node lifecycle events into a live snapshot and fans them out.

    Thread-safe: node events arrive from the engine's asyncio thread, while SSE
    subscribers read from their own threads.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.runs: dict[str, RunState] = {}
        self.last_run_id: str | None = None
        self._subscribers: list[Queue] = []

    # -- subscription (for streaming UIs) ---------------------------------

    def subscribe(self) -> Queue:
        q: Queue = Queue()
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def _emit(self, event: dict) -> None:
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            q.put(event)

    # -- lifecycle (called by the engine) ---------------------------------

    def start_run(self, run_id: str, graph: dict, inputs: dict) -> None:
        nodes = {
            name: NodeRecord(name=name, kind=graph["NodeKinds"].get(name, "?"),
                             deps=[d for d, t in graph["Edges"] if t == name])
            for name in graph["Nodes"]
        }
        # a node supplied directly in inputs is overridden (bypassed)
        for name in graph["Nodes"]:
            if name in inputs:
                nodes[name].status = SKIPPED
                nodes[name].preview = _preview(inputs[name])
        run = RunState(run_id=run_id, graph=graph, inputs=dict(inputs),
                       nodes=nodes, started=time.time())
        with self._lock:
            self.runs[run_id] = run
            self.last_run_id = run_id
        self._emit({"type": "run_start", "run": self.snapshot(run_id)})

    def node_running(self, run_id: str, name: str) -> None:
        rec = self._rec(run_id, name)
        if rec is None:
            return
        rec.status = RUNNING
        rec.started = time.time()
        self._emit({"type": "node", "run_id": run_id, "node": asdict(rec)})

    def node_finished(self, run_id: str, name: str, value: Any,
                      canceled: bool = False, skipped: bool = False,
                      failed: bool = False) -> None:
        rec = self._rec(run_id, name)
        if rec is None:
            return
        rec.ended = time.time()
        if rec.started is not None:
            rec.duration = round(rec.ended - rec.started, 4)
        if canceled:
            rec.status = CANCELED
        elif failed:
            rec.status = ERROR
            rec.error = str(value)[:500]
        elif skipped:
            rec.status = SKIPPED
        else:
            rec.status = DONE
        if not skipped:
            rec.preview = _preview(value)
            rec._full_value = value
        self._emit({"type": "node", "run_id": run_id, "node": asdict(rec)})

    def node_error(self, run_id: str, name: str, err: str) -> None:
        rec = self._rec(run_id, name)
        if rec is None:
            return
        rec.ended = time.time()
        if rec.started is not None:
            rec.duration = round(rec.ended - rec.started, 4)
        rec.status = ERROR
        rec.error = str(err)[:500]
        self._emit({"type": "node", "run_id": run_id, "node": asdict(rec)})

    def note_usage(self, run_id: str, name: str, usage: dict | None) -> None:
        if not usage:
            return
        rec = self._rec(run_id, name)
        if rec is not None:
            rec.usage = usage

    def note_model(self, run_id: str, name: str, model: str | None) -> None:
        """Record which model was used for an LLM node."""
        if not model:
            return
        rec = self._rec(run_id, name)
        if rec is not None:
            rec.model = model

    def node_streaming(self, run_id: str, name: str, chunk: str) -> None:
        """Emit a streaming token chunk for a node."""
        rec = self._rec(run_id, name)
        if rec is None:
            return
        if rec.preview is None:
            rec.preview = ""
        rec.preview += chunk
        self._emit({"type": "node_stream", "run_id": run_id, "node": name, "chunk": chunk})

    def _calculate_cost(self, run: RunState) -> dict | None:
        """Calculate total cost for a run based on token usage and model pricing.
        
        Returns a dict with total cost and per-node breakdown, or None if no
        pricing info is available.
        """
        from .backends import estimate_cost
        
        total_cost = 0.0
        node_costs = {}
        has_pricing = False
        
        for name, rec in run.nodes.items():
            if rec.usage and rec.model:
                input_tokens = rec.usage.get("input_tokens", 0)
                output_tokens = rec.usage.get("output_tokens", 0)
                cost = estimate_cost(rec.model, input_tokens, output_tokens)
                if cost is not None:
                    has_pricing = True
                    total_cost += cost
                    node_costs[name] = {
                        "model": rec.model,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cost_usd": round(cost, 6),
                    }
        
        if not has_pricing:
            return None
        
        return {
            "total_usd": round(total_cost, 6),
            "nodes": node_costs,
        }

    def end_run(self, run_id: str, status: str = DONE, auto_save: bool = True) -> None:
        with self._lock:
            run = self.runs.get(run_id)
            if run is not None:
                run.ended = time.time()
                run.status = status
        self._emit({"type": "run_end", "run": self.snapshot(run_id)})
        if auto_save:
            try:
                self.save_run(run_id)
            except Exception:
                pass  # 持久化失败不影响主流程

    # -- snapshots ---------------------------------------------------------

    def _rec(self, run_id: str, name: str) -> NodeRecord | None:
        with self._lock:
            run = self.runs.get(run_id)
            return run.nodes.get(name) if run else None

    def snapshot(self, run_id: str | None = None) -> dict | None:
        with self._lock:
            run_id = run_id or self.last_run_id
            run = self.runs.get(run_id) if run_id else None
            if run is None:
                return None
            done, total = run.progress()
            cost = self._calculate_cost(run)
            result = {
                "run_id": run.run_id,
                "status": run.status,
                "graph": run.graph,
                "inputs": {k: _preview(v) for k, v in run.inputs.items()},
                "started": run.started,
                "ended": run.ended,
                "elapsed": round((run.ended or time.time()) - run.started, 3),
                "progress": {"done": done, "total": total},
                "nodes": {n: asdict(r) for n, r in run.nodes.items()},
            }
            if cost is not None:
                result["cost"] = cost
            return result

    def get_node_output(self, run_id: str | None, node_name: str) -> dict | None:
        """获取指定节点的完整输出（不截断）"""
        with self._lock:
            run_id = run_id or self.last_run_id
            run = self.runs.get(run_id) if run_id else None
            if run is None:
                return None
            rec = run.nodes.get(node_name)
            if rec is None:
                return None
            return {
                "name": rec.name,
                "status": rec.status,
                "preview": rec.preview,
                "full_value": rec._full_value,
                "error": rec.error,
            }

    def _build_trace(self, run_id: str | None = None) -> dict:
        """Build a trace dict for persistence (used by NotebookManager)."""
        with self._lock:
            run_id = run_id or self.last_run_id
            run = self.runs.get(run_id) if run_id else None
            if run is None:
                raise ValueError(f"No run found for id: {run_id}")

            return {
                "run_id": run.run_id,
                "timestamp": datetime.fromtimestamp(run.started).isoformat(),
                "duration": round((run.ended or time.time()) - run.started, 3),
                "status": run.status,
                "graph": run.graph,
                "input": run.inputs,
                "output": {
                    name: rec._full_value if rec._full_value is not None else rec.preview
                    for name, rec in run.nodes.items()
                    if rec.status == DONE
                },
                "spans": [
                    {
                        "name": rec.name,
                        "kind": rec.kind,
                        "status": rec.status,
                        "start_time": datetime.fromtimestamp(rec.started).isoformat() if rec.started else None,
                        "end_time": datetime.fromtimestamp(rec.ended).isoformat() if rec.ended else None,
                        "duration": rec.duration,
                        "input_deps": rec.deps,
                        "output_preview": rec.preview,
                        "output_full": rec._full_value,
                        "error": rec.error,
                        "tokens": rec.usage,
                        "model": rec.model,
                    }
                    for rec in run.nodes.values()
                ],
            }

    # -- 持久化 -------------------------------------------------------------

    def save_run(self, run_id: str | None = None, output_dir: str = ".llmgraph_runs") -> str:
        """将运行记录保存为 JSON 文件，返回文件路径"""
        trace = self._build_trace(run_id)

        # 写入文件
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / f"{trace['run_id']}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(trace, f, indent=2, ensure_ascii=False, default=str)

        return str(file_path)

    @staticmethod
    def list_runs(output_dir: str = ".llmgraph_runs") -> list[dict]:
        """列出所有历史运行（摘要信息）"""
        out_dir = Path(output_dir)
        if not out_dir.exists():
            return []

        runs = []
        for file_path in sorted(out_dir.glob("*.json"), reverse=True):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    trace = json.load(f)
                runs.append({
                    "run_id": trace["run_id"],
                    "timestamp": trace["timestamp"],
                    "duration": trace["duration"],
                    "status": trace["status"],
                    "input": trace.get("input", {}),
                    "output_summary": {
                        k: (v[:80] + "..." if isinstance(v, str) and len(v) > 80 else v)
                        for k, v in trace.get("output", {}).items()
                    },
                })
            except Exception:
                continue
        return runs

    @staticmethod
    def load_run(run_id: str, output_dir: str = ".llmgraph_runs") -> dict | None:
        """加载指定运行的完整 trace"""
        file_path = Path(output_dir) / f"{run_id}.json"
        if not file_path.exists():
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)


def extract_usage(resp: Any) -> dict | None:
    """Best-effort token usage from a LangChain/LLM response (Wolfram analog:
    ``ChatObject``'s ``Usage``). Returns None if the backend doesn't report it."""
    u = getattr(resp, "usage_metadata", None)
    if isinstance(u, dict) and u:
        return {k: u.get(k) for k in ("input_tokens", "output_tokens", "total_tokens") if k in u}
    meta = getattr(resp, "response_metadata", None)
    if isinstance(meta, dict):
        tu = meta.get("token_usage") or meta.get("usage")
        if isinstance(tu, dict) and tu:
            return tu
    return None
