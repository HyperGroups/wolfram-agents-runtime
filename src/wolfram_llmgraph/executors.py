"""Pluggable execution engines — the **Executor port**.

The semantic core (``LLMGraph``) computes dependencies and per-node *runners*,
then hands a neutral :class:`ExecutionPlan` to an :class:`Executor`. This keeps
**what Wolfram means** (the subset) separate from **how it runs** (the superset).

A *runner* is the neutral contract: ``async (state: dict) -> {name: value}`` — it
reads its dependencies from ``state`` and returns its own ``{name: value}`` (or
``{}`` when the node's value was supplied as an override). Both executors drive
the *same* runners; only **scheduling** differs. So:

* :class:`ReferenceExecutor` — zero-dependency (stdlib asyncio). It is the living
  proof that the semantic core is a true **subset**: it needs no LangGraph, yet
  runs the full Wolfram-compatible semantics (deps, concurrency, override,
  conditional/cancel, failure propagation). It adds **no** superset features.
* :class:`LangGraphExecutor` — compiles onto a LangGraph ``StateGraph``. All
  **superset** capabilities (retries, checkpointing, dynamic topology, loops,
  interrupts) grow *here*, never leaking back into the core.

Switch per graph: ``LLMGraph(..., executor="reference" | "langgraph")``; or set
``$LLMGRAPH_EXECUTOR``. Multiple tech selections coexist as compatible, switchable
variants — the mainline default converges slowly.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol

#: the neutral per-node contract
Runner = Callable[[dict], Awaitable[dict]]


@dataclass
class ExecutionPlan:
    """A neutral, executor-agnostic description of one evaluation."""

    runners: dict[str, Runner]          # name -> async (state) -> {name: value}
    node_deps: dict[str, list[str]]     # name -> node-dep names (scheduling edges)
    sinks: list[str]                    # terminal nodes
    state_fields: list[str]             # all state channel names (nodes ∪ inputs ∪ meta)


class Executor(Protocol):
    name: str

    async def run(self, plan: ExecutionPlan, state: dict) -> dict:
        ...


class ReferenceExecutor:
    """Zero-dependency executor: topological waves + asyncio concurrency.

    Independent nodes in a wave run concurrently (Wolfram's documented
    concurrency). No retries / checkpoints / loops — by design; that is the
    superset's job. This executor's purpose is faithful subset semantics and a
    zero-dependency fallback, plus the parity oracle against the LangGraph one.
    """

    name = "reference"

    async def run(self, plan: ExecutionPlan, state: dict) -> dict:
        results = dict(state)
        done: set[str] = set()
        pending = set(plan.runners)
        while pending:
            ready = [
                n for n in pending
                if all(d in done for d in plan.node_deps.get(n, []))
            ]
            if not ready:
                break  # unsatisfiable deps (a cycle) — a DAG is expected
            outcomes = await asyncio.gather(
                *(self._call(plan, n, results) for n in ready)
            )
            for name, out in outcomes:
                results.update(out)
                done.add(name)
                pending.discard(name)
        return results

    @staticmethod
    async def _call(plan: ExecutionPlan, name: str, state: dict):
        return name, await plan.runners[name](state)


class LangGraphExecutor:
    """Compiles the plan onto a LangGraph ``StateGraph`` (the superset side)."""

    name = "langgraph"

    def compile(self, plan: ExecutionPlan):
        from typing import TypedDict

        from langgraph.graph import END, START, StateGraph

        schema = TypedDict("LLMGraphState", {f: Any for f in plan.state_fields}, total=False)
        g = StateGraph(schema)
        for name, runner in plan.runners.items():
            g.add_node(name, runner)
        for name, deps in plan.node_deps.items():
            if deps:
                for d in deps:
                    g.add_edge(d, name)  # fan-in: waits for every parent
            else:
                g.add_edge(START, name)
        for sink in plan.sinks:
            g.add_edge(sink, END)
        return g.compile()

    async def run(self, plan: ExecutionPlan, state: dict) -> dict:
        return await self.compile(plan).ainvoke(state)


_REGISTRY: dict[str, type] = {
    "reference": ReferenceExecutor,
    "langgraph": LangGraphExecutor,
}

#: mainline default — kept on LangGraph for now; switch freely, converge slowly.
DEFAULT_EXECUTOR = "langgraph"


def get_executor(spec: Any = None) -> Executor:
    """Resolve an executor from ``None`` (→ ``$LLMGRAPH_EXECUTOR`` or default),
    a name (``"reference"``/``"langgraph"``), or an :class:`Executor` instance."""
    if spec is None:
        spec = os.environ.get("LLMGRAPH_EXECUTOR", DEFAULT_EXECUTOR)
    if isinstance(spec, str):
        cls = _REGISTRY.get(spec.lower())
        if cls is None:
            raise ValueError(
                f"unknown executor {spec!r}; choose from {sorted(_REGISTRY)}"
            )
        return cls()
    return spec  # already an Executor instance
