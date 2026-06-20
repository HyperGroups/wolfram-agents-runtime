"""Natural-language task → LLMGraph → result (an LLM-as-compiler planner).

``wolfram_agents do "<task>"``: an LLM turns the task into an ``LLMGraph`` IR, the
runtime executes that graph, and you get the answer. The plan is itself a small
DAG of LLM steps (decompose → … → combine), scheduled concurrently by the runtime.

**Safety:** the planner is constrained to **string-prompt LLM nodes only**. Node
specs containing ``wolfram`` / ``fn`` / ``test`` (which would execute code) are
rejected — model output must not be able to run arbitrary code.

**Robustness:** the plan must also be *runnable* — it must load, its outputs must
exist, and it must be acyclic. If a reply fails any check (bad JSON, disallowed
node, unknown output, cycle), the error is fed back and the planner is asked to
fix it (self-repair, up to ``retries`` times).
"""

from __future__ import annotations

import json
import re
from typing import Any

from .loaders import from_dict

#: keys an NL-planned node may carry (LLM nodes only — no code/wolfram/test)
_ALLOWED_KEYS = {"prompt", "llm", "listable_llm", "model", "input"}

PLANNER_PROMPT = """You are a planner. Decompose the task into an "LLMGraph": a JSON
object describing a small graph of LLM steps that together accomplish the task.

Schema:
{
  "nodes": {
    "StepName": "a prompt telling the LLM what to do for this step",
    "Final":    "combine `StepName` ... into the final answer"
  },
  "output": ["Final"]
}

Rules:
- Each node value MUST be a prompt STRING (one LLM call). NEVER use code,
  functions, or a "wolfram" key.
- A backtick `Name` inside a prompt inserts node Name's output there AND declares
  the dependency. Build a small DAG (2-5 nodes) ending in one clear final node.
- Bake ALL needed context into the prompts; do NOT introduce external inputs.
- Reply with ONLY the JSON object — no prose, no markdown fences.

Task:
{TASK}
"""


def _extract_json(text: str) -> dict:
    """Pull the first balanced JSON object out of an LLM reply (fences/prose ok)."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start = text.find("{")
    if start == -1:
        raise ValueError("planner did not return any JSON object")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("planner returned an unbalanced JSON object")


def validate_ir(ir: Any) -> dict:
    """Reject anything that isn't a graph of plain string-prompt LLM nodes."""
    if not isinstance(ir, dict) or not isinstance(ir.get("nodes"), dict) or not ir["nodes"]:
        raise ValueError("planned IR must be an object with a non-empty 'nodes' map")
    for name, spec in ir["nodes"].items():
        if isinstance(spec, str):
            continue
        if isinstance(spec, dict):
            bad = set(spec) - _ALLOWED_KEYS
            if bad:
                raise ValueError(
                    f"node {name!r}: disallowed keys {sorted(bad)} — the NL planner "
                    f"only allows LLM nodes (prompt strings), not code/wolfram"
                )
            if not (spec.get("prompt") or spec.get("llm") or spec.get("listable_llm")):
                raise ValueError(f"node {name!r}: needs a 'prompt' (LLM node)")
        else:
            raise ValueError(f"node {name!r}: spec must be a prompt string or LLM node")
    return ir


def check_runnable(ir: dict) -> None:
    """Beyond shape: the IR must load, its outputs must exist, and it must be
    acyclic — otherwise the graph would crash or deadlock at run time."""
    graph = from_dict(ir)                       # validates output names / loadability
    color = {n: 0 for n in graph.nodes}         # 0 white, 1 gray, 2 black
    deps = {n: graph.nodes[n].node_deps for n in graph.nodes}

    def visit(n: str):
        color[n] = 1
        for d in deps[n]:
            if color[d] == 1:
                raise ValueError(f"planned graph has a cycle through {n!r} -> {d!r}")
            if color[d] == 0:
                visit(d)
        color[n] = 2

    for n in graph.nodes:
        if color[n] == 0:
            visit(n)


def plan_graph(task: str, *, backend: str | None = None, model: str | None = None,
               llm_factory=None, retries: int = 2) -> dict:
    """Ask the LLM to compile ``task`` into a validated LLMGraph IR (JSON).

    Self-repairing: if the reply isn't valid JSON / a safe, runnable graph, the
    error is fed back and the planner is asked to fix it, up to ``retries`` times.
    """
    from .synthesize import LLMSynthesize

    prompt = PLANNER_PROMPT.replace("{TASK}", task)
    last_err: Exception | None = None
    last_raw = ""
    for _ in range(retries + 1):
        raw = LLMSynthesize(prompt, backend=backend, model=model, llm_factory=llm_factory)
        last_raw = raw
        try:
            ir = validate_ir(_extract_json(raw))
            check_runnable(ir)
            return ir
        except Exception as exc:  # noqa: BLE001 — feed any failure back to the planner
            last_err = exc
            prompt = (
                PLANNER_PROMPT.replace("{TASK}", task)
                + f"\n\nYour previous reply was INVALID: {exc}\n"
                  f"Previous reply (fix it):\n{raw[:800]}\n"
                  f"Return ONLY a corrected JSON object that obeys all the rules."
            )
    raise ValueError(
        f"planner failed after {retries + 1} attempt(s): {last_err}\n"
        f"last reply was:\n{last_raw[:400]}"
    )


def run_task(task: str, *, backend: str | None = None, model: str | None = None,
             prop: Any = None, llm_factory=None, retries: int = 2) -> tuple[dict, Any]:
    """Plan ``task`` into a graph, run it, and return ``(ir, result)``."""
    ir = plan_graph(task, backend=backend, model=model,
                    llm_factory=llm_factory, retries=retries)
    graph = from_dict(ir)
    if backend:
        graph.backend = backend
    if model:
        graph.model = model
    if llm_factory is not None:
        graph._llm_factory = llm_factory
    # a self-contained plan has no inputs; if it declares exactly one, feed the task
    inputs = {graph.inputs[0]: task} if len(graph.inputs) == 1 else {}
    return ir, graph(inputs, prop)
