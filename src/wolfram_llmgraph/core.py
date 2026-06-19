"""Core engine for the Wolfram-style LLMGraph runtime.

This mirrors the programming model of Wolfram Language's ``LLMGraph``:

* A graph is an association (dict) of named nodes ``{"name": spec, ...}``.
* A node's function evaluates on the outputs of its *parent* nodes.
* Dependencies are inferred automatically:
    - For a prompt string, every ``` `Slot` ``` reference names a parent node
      (or an input argument supplied at evaluation time).
    - For a Python callable, the parameter names are the parents.
* A node starts as soon as all its dependencies are available; independent
  nodes run concurrently. Scheduling/concurrency is handled by LangGraph.
* ``graph(input)`` runs the graph. ``input`` is a dict mapping input-argument
  names (and optional intermediate-node overrides) to values.
* ``graph(input, prop)`` selects a property:
    - ``None`` / ``"Automatic"`` -> output nodes (single output is unwrapped),
    - ``"All"``                  -> every node's result,
    - ``"Graph"``                -> the static graph structure,
    - ``"name"``                 -> that one node's result (unwrapped),
    - ``["a", "b", ...]``        -> an association of just those nodes.

Supported node specs (MVP):
    "prompt string"                                    -> LLM node (StringTemplate-style)
    python_callable                                    -> code node (Wolfram kernel analog)
    {"prompt": "...", "model": "..."}                  -> LLM node with model
    {"prompt": "...", "model": "...", "backend": "..."} -> LLM node with per-node backend
    {"fn": callable, "input": [...]}                   -> code node with explicit parents

Any mapping spec may add ``"test"`` (a WL code string or a callable) plus
``"test_input"`` to make a conditional node (Wolfram ``ConditionalNode``): the
node only evaluates when the test is truthy, otherwise it yields
:class:`CanceledNode` (``Missing["CanceledNode", name]``) and is skipped.
"""

from __future__ import annotations

import asyncio
import inspect
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

DEFAULT_MODEL = "claude-opus-4-8"

# A slot is a backtick-wrapped identifier, e.g. `Poet1`, matching Wolfram's
# StringTemplate slot syntax used inside LLMGraph prompt nodes.
_SLOT_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")

# Wolfram compute nodes reference dependencies as deps["name"] (backticks are
# WL context separators, so slot syntax isn't usable inside WL code).
_WOLFRAM_DEP_RE = re.compile(r'deps\[\s*["\']([A-Za-z_][A-Za-z0-9_]*)["\']\s*\]')

_PROVIDED_KEY = "__provided__"


@dataclass(frozen=True)
class CanceledNode:
    """Value of a conditional node whose ``test`` predicate failed.

    Mirrors Wolfram's ``Missing["CanceledNode", name]``: the node is skipped but
    still appears in the results carrying this sentinel. Renders to the same
    text Wolfram exports, so it compares equal across engines.
    """

    node: str

    def __repr__(self) -> str:
        return f"Missing[CanceledNode, {self.node}]"

    __str__ = __repr__


@dataclass(frozen=True)
class FailedNode:
    """Value of a node that failed (e.g., Wolfram $Failed or dependency failure).

    Propagates through the graph: downstream nodes that depend on a FailedNode
    or CanceledNode also receive FailedNode (unless they handle it explicitly).
    """

    node: str
    reason: str = ""

    def __repr__(self) -> str:
        if self.reason:
            return f"Failed[{self.node}, {self.reason!r}]"
        return f"Failed[{self.node}]"

    __str__ = __repr__


def is_canceled(value: Any) -> bool:
    """True if ``value`` is a :class:`CanceledNode` sentinel."""
    return isinstance(value, CanceledNode)


def is_failed(value: Any) -> bool:
    """True if ``value`` is a :class:`FailedNode` sentinel."""
    return isinstance(value, FailedNode)


def is_propagated(value: Any) -> bool:
    """True if ``value`` is a CanceledNode or FailedNode (should propagate)."""
    return isinstance(value, (CanceledNode, FailedNode))


def _slots(template: str) -> list[str]:
    """Return the ordered, de-duplicated slot names referenced in a template."""
    seen: dict[str, None] = {}
    for name in _SLOT_RE.findall(template):
        seen.setdefault(name, None)
    return list(seen)


def _wolfram_deps(code: str) -> list[str]:
    """Dependency names referenced as deps["name"] in Wolfram compute code."""
    seen: dict[str, None] = {}
    for name in _WOLFRAM_DEP_RE.findall(code):
        seen.setdefault(name, None)
    return list(seen)


@dataclass
class Node:
    """A single node in an LLMGraph."""

    name: str
    kind: str  # "llm" | "listable_llm" | "fn" | "wolfram"
    template: str | None = None
    fn: Callable[..., Any] | None = None
    code: str | None = None  # for "wolfram" nodes
    model: str | None = None
    backend: str | None = None
    deps: list[str] = field(default_factory=list)
    # Conditional node (Wolfram ConditionalNode): the node only evaluates when
    # ``test`` is truthy, else it yields CanceledNode. ``test`` is a WL code
    # string (run in the kernel) or a Python callable; ``test_deps`` are its
    # arguments (Wolfram's InputTestFunction), and are merged into ``deps``.
    test: Any = None
    test_deps: list[str] = field(default_factory=list)
    # ListableLLMFunction: maps LLM calls over list inputs in parallel.
    # ``list_inputs`` are the dependency names that should be lists; the template
    # is evaluated once per element (zipped if multiple lists).
    list_inputs: list[str] = field(default_factory=list)
    # Filled in by LLMGraph once all node names are known:
    node_deps: list[str] = field(default_factory=list)
    input_deps: list[str] = field(default_factory=list)


def _callable_params(fn: Callable[..., Any]) -> list[str]:
    """Positional/keyword parameter names of ``fn`` — these are its parents."""
    params = []
    for p in inspect.signature(fn).parameters.values():
        if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY):
            params.append(p.name)
    return params


def _attach_test(node: Node, test: Any, test_input: Any) -> None:
    """Attach a conditional ``test`` to ``node`` and merge its deps in."""
    if isinstance(test, str):
        tdeps = list(test_input) if test_input is not None else _wolfram_deps(test)
    elif callable(test):
        tdeps = list(test_input) if test_input is not None else _callable_params(test)
    else:
        raise TypeError(
            f"Node {node.name!r}: 'test' must be a WL code string or a callable"
        )
    node.test = test
    node.test_deps = tdeps  # kept separate from eval deps; both wire the graph


def parse_node(name: str, spec: Any) -> Node:
    """Turn a user-supplied node spec into a :class:`Node`."""
    if isinstance(spec, str):
        return Node(name, "llm", template=spec, deps=_slots(spec))

    if callable(spec):
        return Node(name, "fn", fn=spec, deps=_callable_params(spec))

    if isinstance(spec, Mapping):
        model = spec.get("model")
        backend = spec.get("backend")
        if "wolfram" in spec:
            code = spec["wolfram"]
            if not isinstance(code, str):
                raise TypeError(f"Node {name!r}: 'wolfram' must be a code string")
            deps = list(spec.get("input") or _wolfram_deps(code))
            node = Node(name, "wolfram", code=code, deps=deps)
        elif "listable_llm" in spec:
            template = spec["listable_llm"]
            if not isinstance(template, str):
                raise TypeError(f"Node {name!r}: 'listable_llm' must be a prompt string")
            deps = list(spec.get("input") or _slots(template))
            if not deps:
                raise ValueError(
                    f"Node {name!r}: 'listable_llm' needs 'input' listing the list-valued deps"
                )
            node = Node(
                name, "listable_llm", template=template,
                model=model, backend=backend, deps=deps, list_inputs=deps,
            )
        elif "fn" in spec or "function" in spec:
            fn = spec.get("fn") or spec.get("function")
            if not callable(fn):
                raise TypeError(f"Node {name!r}: 'fn' must be callable")
            deps = list(spec.get("input") or _callable_params(fn))
            node = Node(name, "fn", fn=fn, model=model, backend=backend, deps=deps)
        else:
            template = spec.get("prompt") or spec.get("llm") or spec.get("template")
            if template is None:
                raise ValueError(
                    f"Node {name!r}: spec must contain 'prompt', 'listable_llm', or 'fn'"
                )
            deps = list(spec.get("input") or _slots(template))
            node = Node(name, "llm", template=template, model=model, backend=backend, deps=deps)

        if spec.get("test") is not None:
            _attach_test(node, spec["test"], spec.get("test_input"))
        return node

    raise TypeError(
        f"Node {name!r}: unsupported spec of type {type(spec).__name__}"
    )


class LLMGraph:
    """A declarative graph of LLM and code nodes, compiled onto LangGraph.
    
    Args:
        nodes: Node specifications
        output: Output node names (defaults to sinks)
        model: Default LLM model
        backend: LLM backend name
        llm_factory: Custom LLM factory function
        monitor: RunMonitor for observability
        speculative: If True, conditional nodes execute LLM in parallel with
            test evaluation (Wolfram semantics). If False, wait for test deps
            before executing (default).
    """

    def __init__(
        self,
        nodes: Mapping[str, Any],
        *,
        output: Sequence[str] | None = None,
        model: str | None = None,
        backend: str | None = None,
        backend_strict: bool = False,
        llm_factory: Callable[[str], Any] | None = None,
        monitor: Any = None,
        speculative: bool = False,
    ) -> None:
        if not nodes:
            raise ValueError("An LLMGraph needs at least one node")

        from .backends import resolve_backend
        self.model = model
        self.backend = resolve_backend(backend, strict=backend_strict)
        self.backend_strict = backend_strict
        self._llm_factory = llm_factory
        self._llms: dict[tuple[str | None, str | None], Any] = {}
        self._wolfram_compute = None
        self._compiled = None
        # Observability: an optional RunMonitor receives node lifecycle events.
        self.monitor = monitor
        self._run_id: str | None = None
        # Execution mode: speculative (Wolfram) vs sequential
        self.speculative = speculative

        self.nodes: dict[str, Node] = {
            name: parse_node(name, spec) for name, spec in nodes.items()
        }
        self.node_names = set(self.nodes)

        # Classify each declared dependency as a node-dep or an input argument.
        # For graph structure (scheduling):
        # - speculative: only eval_deps (test_deps checked after execution)
        # - sequential: eval_deps + test_deps (wait for both before execution)
        for nd in self.nodes.values():
            if self.speculative and nd.test is not None:
                # Wolfram semantics: graph based on eval deps only
                # test_deps are checked after execution, not for scheduling
                graph_deps = nd.deps
            else:
                # Sequential: merge test deps into graph deps
                graph_deps = nd.deps + [d for d in nd.test_deps if d not in nd.deps]
            
            nd.node_deps = [d for d in graph_deps if d in self.node_names]
            nd.input_deps = [d for d in graph_deps if d not in self.node_names]

        # Input arguments: referenced names that are not themselves nodes.
        self.inputs = sorted(
            {d for nd in self.nodes.values() for d in nd.input_deps}
        )

        # Sinks (nodes nobody depends on) are the default outputs.
        referenced = {d for nd in self.nodes.values() for d in nd.node_deps}
        self.sinks = [n for n in self.nodes if n not in referenced]
        self.outputs = list(output) if output else list(self.sinks)
        for o in self.outputs:
            if o not in self.node_names:
                raise ValueError(f"Output {o!r} is not a node")

    # -- compilation -------------------------------------------------------

    def _state_schema(self):
        # One channel per node/input so independent nodes can write
        # concurrently (a single dict channel would force one write/superstep).
        from typing import TypedDict

        fields = {name: Any for name in self.node_names}
        for arg in self.inputs:
            fields[arg] = Any
        fields[_PROVIDED_KEY] = Any
        return TypedDict("LLMGraphState", fields, total=False)

    def _build(self):
        from langgraph.graph import END, START, StateGraph

        g = StateGraph(self._state_schema())
        for nd in self.nodes.values():
            g.add_node(nd.name, self._make_runner(nd))

        for nd in self.nodes.values():
            if nd.node_deps:
                for d in nd.node_deps:
                    g.add_edge(d, nd.name)  # fan-in: waits for every parent
            else:
                g.add_edge(START, nd.name)

        for sink in self.sinks:
            g.add_edge(sink, END)

        return g.compile()

    def _llm(self, backend: str | None, model: str | None):
        b = backend or self.backend
        m = model or self.model
        key = (b, m)
        if key not in self._llms:
            if self._llm_factory is not None:
                self._llms[key] = self._llm_factory(m)
            else:
                from .backends import make_llm

                self._llms[key] = make_llm(b, m)
        return self._llms[key]

    def _wolfram(self):
        if self._wolfram_compute is None:
            from .compute import WolframCompute

            self._wolfram_compute = WolframCompute()
        return self._wolfram_compute

    async def _eval_test(self, nd: Node, state: dict) -> bool:
        """Evaluate a conditional node's ``test`` predicate over its deps."""
        if callable(nd.test):
            kwargs = {d: state.get(d) for d in nd.test_deps}
            res = nd.test(**kwargs)
            if inspect.isawaitable(res):
                res = await res
            return bool(res)
        # WL code string -> evaluate in the kernel (returns a JSON-able value).
        inputs = {d: state.get(d) for d in nd.test_deps}
        res = await self._wolfram().run(nd.test, inputs)
        return res is not False and bool(res)

    def _make_runner(self, nd: Node):
        base = self._base_runner(nd)
        if nd.test is not None:
            inner = base

            if self.speculative:
                # Wolfram semantics: execute first, then test
                # This allows LLM to run in parallel with other nodes,
                # then decide whether to keep the result
                async def speculative_gated(state: dict) -> dict:
                    if nd.name in state.get(_PROVIDED_KEY, ()):  # override bypass
                        return {}
                    # Execute the node first (LLM call, etc.)
                    result = await inner(state)
                    # Then evaluate the test
                    if not await self._eval_test(nd, state):
                        # Test failed: discard result, return CanceledNode
                        return {nd.name: CanceledNode(nd.name)}
                    # Test passed: keep the result
                    return result

                runner = speculative_gated
            else:
                # Sequential semantics: test first, then execute
                async def gated(state: dict) -> dict:  # conditional gate
                    if nd.name in state.get(_PROVIDED_KEY, ()):  # override bypass
                        return {}
                    if not await self._eval_test(nd, state):
                        return {nd.name: CanceledNode(nd.name)}
                    return await inner(state)

                runner = gated
        else:
            runner = base

        if self.monitor is None:
            return runner
        return self._monitored(nd, runner)

    def _monitored(self, nd: Node, runner):
        """Wrap a runner to emit node lifecycle events to ``self.monitor``."""

        async def run(state: dict) -> dict:
            if nd.name in state.get(_PROVIDED_KEY, ()):  # overridden -> already SKIPPED
                return await runner(state)
            self.monitor.node_running(self._run_id, nd.name)
            try:
                out = await runner(state)
            except Exception as exc:  # surface the failure on the node
                self.monitor.node_error(self._run_id, nd.name, repr(exc))
                raise
            val = out.get(nd.name)
            self.monitor.node_finished(
                self._run_id, nd.name, val,
                canceled=is_canceled(val),
                failed=is_failed(val),
            )
            return out

        return run

    def _check_dep_failures(self, nd: Node, state: dict) -> Any | None:
        """Check if any node-dep has a propagated failure. Returns sentinel or None."""
        for dep in nd.node_deps:
            val = state.get(dep)
            if isinstance(val, CanceledNode):
                return CanceledNode(nd.name)
            if isinstance(val, FailedNode):
                return FailedNode(nd.name, f"upstream: {dep}")
        return None

    def _base_runner(self, nd: Node):
        if nd.kind == "llm":

            async def run(state: dict) -> dict:
                if nd.name in state.get(_PROVIDED_KEY, ()):  # override bypass
                    return {}
                propagated = self._check_dep_failures(nd, state)
                if propagated is not None:
                    return {nd.name: propagated}
                prompt = _SLOT_RE.sub(
                    lambda m: str(state.get(m.group(1), "")), nd.template
                )
                llm = self._llm(nd.backend, nd.model)
                
                if self.monitor is not None and hasattr(llm, "astream"):
                    try:
                        full_content = []
                        async for chunk, is_final in llm.astream(prompt):
                            full_content.append(chunk)
                            self.monitor.node_streaming(self._run_id, nd.name, chunk)
                        content = "".join(full_content)
                        model_name = nd.model or getattr(llm, "model", None) or getattr(llm, "model_name", None)
                        self.monitor.note_model(self._run_id, nd.name, model_name)
                        return {nd.name: content}
                    except (NotImplementedError, AttributeError):
                        pass
                
                resp = await llm.ainvoke(prompt)
                if self.monitor is not None:
                    from .monitor import extract_usage

                    self.monitor.note_usage(
                        self._run_id, nd.name, extract_usage(resp)
                    )
                    model_name = nd.model or getattr(llm, "model", None) or getattr(llm, "model_name", None)
                    self.monitor.note_model(self._run_id, nd.name, model_name)
                content = getattr(resp, "content", resp)
                return {nd.name: content}

            return run

        if nd.kind == "listable_llm":

            async def run(state: dict) -> dict:
                if nd.name in state.get(_PROVIDED_KEY, ()):
                    return {}
                propagated = self._check_dep_failures(nd, state)
                if propagated is not None:
                    return {nd.name: propagated}
                lists = {d: state.get(d, []) for d in nd.list_inputs}
                for d in nd.list_inputs:
                    if not isinstance(lists[d], (list, tuple)):
                        raise TypeError(
                            f"Node {nd.name!r}: listable_llm dep {d!r} must be a list, "
                            f"got {type(lists[d]).__name__}"
                        )
                lengths = [len(lists[d]) for d in nd.list_inputs]
                if len(set(lengths)) != 1:
                    raise ValueError(
                        f"Node {nd.name!r}: listable_llm deps have mismatched lengths: "
                        f"{dict(zip(nd.list_inputs, lengths))}"
                    )
                n = lengths[0] if lengths else 0
                results = [None] * n
                llm = self._llm(nd.backend, nd.model)
                model_name = nd.model or getattr(llm, "model", None) or getattr(llm, "model_name", None)

                async def _one(idx: int):
                    local_state = dict(state)
                    for d in nd.list_inputs:
                        local_state[d] = lists[d][idx]
                    prompt = _SLOT_RE.sub(
                        lambda m: str(local_state.get(m.group(1), "")), nd.template
                    )
                    resp = await llm.ainvoke(prompt)
                    return resp

                tasks = [_one(i) for i in range(n)]
                responses = list(await asyncio.gather(*tasks))
                
                if self.monitor is not None:
                    from .monitor import extract_usage
                    total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
                    for resp in responses:
                        u = extract_usage(resp)
                        if u:
                            total_usage["input_tokens"] += u.get("input_tokens", 0)
                            total_usage["output_tokens"] += u.get("output_tokens", 0)
                            total_usage["total_tokens"] += u.get("total_tokens", 0)
                    self.monitor.note_usage(self._run_id, nd.name, total_usage)
                    self.monitor.note_model(self._run_id, nd.name, model_name)
                
                results = [getattr(r, "content", r) for r in responses]
                return {nd.name: results}

            return run

        if nd.kind == "wolfram":

            async def run(state: dict) -> dict:  # Wolfram compute node
                if nd.name in state.get(_PROVIDED_KEY, ()):
                    return {}
                propagated = self._check_dep_failures(nd, state)
                if propagated is not None:
                    return {nd.name: propagated}
                inputs = {d: state.get(d) for d in nd.deps}
                try:
                    result = await self._wolfram().run(nd.code, inputs)
                except RuntimeError as exc:
                    return {nd.name: FailedNode(nd.name, str(exc))}
                return {nd.name: result}

            return run

        async def run(state: dict) -> dict:  # code node
            if nd.name in state.get(_PROVIDED_KEY, ()):
                return {}
            propagated = self._check_dep_failures(nd, state)
            if propagated is not None:
                return {nd.name: propagated}
            kwargs = {d: state.get(d) for d in nd.deps}
            result = nd.fn(**kwargs)
            if inspect.isawaitable(result):
                result = await result
            return {nd.name: result}

        return run

    # -- evaluation --------------------------------------------------------

    async def ainvoke(self, input: Mapping[str, Any] | None = None, prop: Any = None):
        data = dict(input or {})
        provided = {k for k in data if k in self.node_names}
        state = dict(data)
        state[_PROVIDED_KEY] = provided

        if self._compiled is None:
            self._compiled = self._build()

        if self.monitor is not None:
            self._run_id = uuid.uuid4().hex[:12]
            self.monitor.start_run(self._run_id, self.information(), data)
            try:
                final = await self._compiled.ainvoke(state)
            except Exception:
                self.monitor.end_run(self._run_id, status="error")
                raise
            self.monitor.end_run(self._run_id, status="done")
        else:
            final = await self._compiled.ainvoke(state)

        final = {k: v for k, v in final.items() if not k.startswith("__")}
        return self._select(final, prop)

    def __call__(self, input: Mapping[str, Any] | None = None, prop: Any = None):
        return asyncio.run(self.ainvoke(input, prop))

    def _select(self, final: dict, prop: Any):
        # Property selection, mirroring Wolfram ``LLMGraph[...][input, prop]``:
        #   None / "Automatic"   -> output nodes (a single output is unwrapped)
        #   "All"                -> every node's result
        #   "Graph"              -> the static graph structure (information())
        #   "name"               -> that one node's result (unwrapped)
        #   ["a", "b", ...]      -> an association of just those nodes
        # Reserved keywords win over identically-named nodes, as in Wolfram.
        if prop in (None, "Automatic", "automatic", "auto"):
            outs = {k: final.get(k) for k in self.outputs}
            if len(outs) == 1:
                return next(iter(outs.values()))
            return outs
        if prop in ("All", "all"):
            return final
        if prop in ("Graph", "graph"):
            return self.information()
        if isinstance(prop, str):
            if prop in self.node_names:
                return final.get(prop)
            raise ValueError(
                f"Unknown property {prop!r}: use None, 'All', 'Graph', a node "
                f"name, or a list of node names. Nodes: {sorted(self.node_names)}"
            )
        if isinstance(prop, (list, tuple)):
            missing = [p for p in prop if p not in self.node_names]
            if missing:
                raise ValueError(
                    f"Not nodes: {missing}. Nodes: {sorted(self.node_names)}"
                )
            return {p: final.get(p) for p in prop}
        raise ValueError(
            f"Unknown property: {prop!r} (use None, 'All', 'Graph', a node "
            f"name, or a list of node names)"
        )

    # -- introspection -----------------------------------------------------

    def information(self) -> dict:
        """Static graph info, analogous to ``Information[LLMGraph[...]]``."""
        return {
            "Nodes": list(self.nodes),
            "Inputs": list(self.inputs),
            "Outputs": list(self.outputs),
            "Edges": [
                (d, nd.name)
                for nd in self.nodes.values()
                for d in nd.node_deps
            ],
            # input-argument -> node edges (Wolfram draws these as input vertices)
            "InputEdges": [
                (d, nd.name)
                for nd in self.nodes.values()
                for d in nd.input_deps
            ],
            "NodeKinds": {n: nd.kind for n, nd in self.nodes.items()},
        }

    def langgraph_structure(self) -> dict:
        """The *compiled* LangGraph our runtime builds — the actual execution
        graph (``__start__`` / ``__end__`` + fan-in edges), plus LangGraph's own
        Mermaid export. This is the runtime layer beneath the LLMGraph layer."""
        if self._compiled is None:
            self._compiled = self._build()
        g = self._compiled.get_graph()
        out = {
            "nodes": list(g.nodes),
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "conditional": bool(getattr(e, "conditional", False)),
                }
                for e in g.edges
            ],
        }
        try:
            out["mermaid"] = g.draw_mermaid()
        except Exception:  # mermaid rendering is best-effort
            out["mermaid"] = None
        return out

    def __repr__(self) -> str:
        return (
            f"LLMGraph(nodes={list(self.nodes)}, "
            f"inputs={self.inputs}, outputs={self.outputs})"
        )
