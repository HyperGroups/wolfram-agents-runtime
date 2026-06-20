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
    - ``"LLMGraph"``             -> the structure *annotated with the results*
                                    (only the nodes whose dependencies were
                                    satisfied are assigned a result),
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

from .prompts import (
    PromptLibrary,
    default_library,
    is_prompt_spec,
    normalize_prompt,
)

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
    # Per-node LLMConfiguration overrides (temperature/max_tokens/stop/system),
    # merged over the graph-level ``llm_config`` (Wolfram's LLMEvaluator).
    config: dict = field(default_factory=dict)
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


_CONFIG_KEYS = ("temperature", "max_tokens", "stop", "system", "top_p")


def _node_config_from_spec(spec: Mapping) -> dict:
    return {k: spec[k] for k in _CONFIG_KEYS if k in spec}


def parse_node(name: str, spec: Any, library: PromptLibrary | None = None) -> Node:
    """Turn a user-supplied node spec into a :class:`Node`."""
    library = library or default_library()

    if isinstance(spec, str):
        return Node(name, "llm", template=spec, deps=_slots(spec))

    # list of strings / LLMPrompt / TemplateObject as a bare node spec
    if is_prompt_spec(spec) and not isinstance(spec, Mapping):
        tmpl = normalize_prompt(spec, library)
        return Node(name, "llm", template=tmpl, deps=_slots(tmpl))

    if callable(spec):
        return Node(name, "fn", fn=spec, deps=_callable_params(spec))

    if isinstance(spec, Mapping):
        model = spec.get("model")
        backend = spec.get("backend")
        config = _node_config_from_spec(spec)
        if "wolfram" in spec:
            code = spec["wolfram"]
            if not isinstance(code, str):
                raise TypeError(f"Node {name!r}: 'wolfram' must be a code string")
            deps = list(spec.get("input") or _wolfram_deps(code))
            node = Node(name, "wolfram", code=code, deps=deps)
        elif "listable_llm" in spec:
            template = normalize_prompt(spec["listable_llm"], library)
            deps = list(spec.get("input") or _slots(template))
            if not deps:
                raise ValueError(
                    f"Node {name!r}: 'listable_llm' needs 'input' listing the list-valued deps"
                )
            node = Node(
                name, "listable_llm", template=template,
                model=model, backend=backend, config=config, deps=deps, list_inputs=deps,
            )
        elif "fn" in spec or "function" in spec:
            fn = spec.get("fn") or spec.get("function")
            if not callable(fn):
                raise TypeError(f"Node {name!r}: 'fn' must be callable")
            deps = list(spec.get("input") or _callable_params(fn))
            node = Node(name, "fn", fn=fn, model=model, backend=backend, deps=deps)
        else:
            raw = spec.get("prompt") or spec.get("llm") or spec.get("template")
            if raw is None and ("llm_prompt" in spec or "template_object" in spec):
                raw = spec  # _from_json picks up llm_prompt / template_object
            if raw is None:
                raise ValueError(
                    f"Node {name!r}: spec must contain 'prompt', 'listable_llm', "
                    f"'llm_prompt', 'template_object', or 'fn'"
                )
            template = normalize_prompt(raw, library)
            deps = list(spec.get("input") or _slots(template))
            node = Node(name, "llm", template=template, model=model,
                        backend=backend, config=config, deps=deps)

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
        llm_config: Mapping[str, Any] | None = None,
        authentication: Any = None,
        prompts: PromptLibrary | None = None,
        executor: Any = None,
    ) -> None:
        if not nodes:
            raise ValueError("An LLMGraph needs at least one node")

        from .backends import resolve_backend
        self.model = model
        self.backend = resolve_backend(backend, strict=backend_strict)
        self.backend_strict = backend_strict
        # LLMEvaluator: graph-level default LLMConfiguration (per-node overrides).
        self.llm_config = dict(llm_config or {})
        # Authentication option: None/"Environment" (env), {"api_key": ...},
        # {"env": "VARNAME"} (Wolfram SystemCredentialKey analog).
        self.authentication = authentication
        # Prompt library (our Wolfram Prompt Repository counterpart for LLMPrompt).
        self._prompt_library = prompts or default_library()
        self._llm_factory = llm_factory
        self._llms: dict[tuple[str | None, str | None], Any] = {}
        self._wolfram_compute = None
        # Observability: an optional RunMonitor receives node lifecycle events.
        self.monitor = monitor
        self._run_id: str | None = None
        # Execution mode: speculative (Wolfram) vs sequential
        self.speculative = speculative
        # Executor port: which engine runs the plan — "langgraph" (default) or
        # "reference" (zero-dep) or an Executor instance. The semantic core is
        # executor-agnostic; superset features live only in the LangGraph one.
        self.executor = executor

        self.nodes: dict[str, Node] = {
            name: parse_node(name, spec, self._prompt_library)
            for name, spec in nodes.items()
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

    # -- planning ----------------------------------------------------------

    def _make_plan(self):
        """Build the neutral :class:`~.executors.ExecutionPlan` for an Executor.

        Each node's runner is the executor-agnostic contract
        ``async (state) -> {name: value}``; both executors drive these same
        runners, differing only in scheduling.
        """
        from .executors import ExecutionPlan

        return ExecutionPlan(
            runners={nd.name: self._make_runner(nd) for nd in self.nodes.values()},
            node_deps={nd.name: list(nd.node_deps) for nd in self.nodes.values()},
            sinks=list(self.sinks),
            state_fields=[*self.node_names, *self.inputs, _PROVIDED_KEY],
        )

    def _node_config(self, nd: Node) -> dict:
        """Effective LLMConfiguration: graph defaults overridden by the node."""
        return {**self.llm_config, **nd.config}

    def _auth_key(self) -> str | None:
        """Resolve an explicit API key from the ``authentication`` option.

        None / "Automatic" / "Environment" -> None (backend uses env). A mapping
        ``{"api_key": ...}`` or ``{"env": "VARNAME"}`` supplies/locates the key.
        SystemCredential / ServiceObject are WL-specific -> fall back to env.
        """
        a = self.authentication
        if isinstance(a, Mapping):
            if a.get("api_key"):
                return a["api_key"]
            if a.get("env"):
                import os

                return os.environ.get(a["env"])
        return None

    def _llm(self, backend: str | None, model: str | None, config: Mapping | None = None):
        b = backend or self.backend
        m = model or self.model
        # only the constructor-level config affects the client object
        cfg = {k: v for k, v in (config or {}).items()
               if k in ("temperature", "max_tokens", "stop", "top_p")}
        api_key = self._auth_key()
        key = (b, m, repr(sorted(cfg.items())), api_key)
        if key not in self._llms:
            if self._llm_factory is not None:
                self._llms[key] = self._llm_factory(m)
            else:
                from .backends import make_llm

                self._llms[key] = make_llm(b, m, config=cfg, api_key=api_key)
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
                cfg = self._node_config(nd)
                prompt = _SLOT_RE.sub(
                    lambda m: str(state.get(m.group(1), "")), nd.template
                )
                if cfg.get("system"):
                    prompt = f"{cfg['system']}\n\n{prompt}"
                llm = self._llm(nd.backend, nd.model, cfg)

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
                cfg = self._node_config(nd)
                llm = self._llm(nd.backend, nd.model, cfg)
                model_name = nd.model or getattr(llm, "model", None) or getattr(llm, "model_name", None)

                async def _one(idx: int):
                    local_state = dict(state)
                    for d in nd.list_inputs:
                        local_state[d] = lists[d][idx]
                    prompt = _SLOT_RE.sub(
                        lambda m: str(local_state.get(m.group(1), "")), nd.template
                    )
                    if cfg.get("system"):
                        prompt = f"{cfg['system']}\n\n{prompt}"
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

    async def ainvoke(self, input: Any = None, prop: Any = None):
        if input is None:
            data: dict[str, Any] = {}
        elif isinstance(input, Mapping):
            data = dict(input)
        else:
            # a bare value for the single graph input (Wolfram: ``g[val]``)
            if len(self.inputs) != 1:
                raise ValueError(
                    f"a bare input value requires exactly one graph input; this "
                    f"graph's inputs are {self.inputs}. Pass a dict instead."
                )
            data = {self.inputs[0]: input}
        provided = {k for k in data if k in self.node_names}
        state = dict(data)
        state[_PROVIDED_KEY] = provided

        from .executors import get_executor

        executor = get_executor(self.executor)
        plan = self._make_plan()

        if self.monitor is not None:
            self._run_id = uuid.uuid4().hex[:12]
            self.monitor.start_run(self._run_id, self.information(), data)
            try:
                final = await executor.run(plan, state)
            except Exception:
                self.monitor.end_run(self._run_id, status="error")
                raise
            self.monitor.end_run(self._run_id, status="done")
        else:
            final = await executor.run(plan, state)

        final = {k: v for k, v in final.items() if not k.startswith("__")}
        return self._select(final, prop, data)

    def __call__(self, input: Any = None, prop: Any = None):
        return asyncio.run(self.ainvoke(input, prop))

    def submit(self, input: Any = None, target: Any = "Automatic", *,
               handlers: Any = None, handler_keys: Any = "Automatic"):
        """Asynchronous evaluation — Wolfram ``LLMGraphSubmit``. Returns a Task."""
        from .submit import LLMGraphSubmit

        return LLMGraphSubmit(self, input, target,
                              handlers=handlers, handler_keys=handler_keys)

    def _evaluable(self, data: Mapping[str, Any]) -> set:
        """Nodes whose dependencies are satisfied given the supplied ``data``.

        A node is evaluable if it is itself provided (overridden), or every one
        of its input-argument deps is supplied *and* every node-dep is itself
        evaluable. Mirrors Wolfram's partial evaluation: with some inputs
        missing, only a subset of nodes is assigned a result.
        """
        provided_inputs = {k for k in data if k in self.inputs}
        provided_nodes = {k for k in data if k in self.node_names}
        memo: dict[str, bool] = {}

        def can(n: str) -> bool:
            if n in memo:
                return memo[n]
            if n in provided_nodes:
                memo[n] = True
                return True
            nd = self.nodes[n]
            memo[n] = True  # guard cycles (DAG expected)
            memo[n] = all(d in provided_inputs for d in nd.input_deps) and all(
                can(d) for d in nd.node_deps
            )
            return memo[n]

        return {n for n in self.nodes if can(n)}

    def _select(self, final: dict, prop: Any, data: Mapping[str, Any] | None = None):
        # Property selection, mirroring Wolfram ``LLMGraph[...][input, prop]``:
        #   None / "Automatic"   -> output nodes (a single output is unwrapped)
        #   "All"                -> every node's result
        #   "Graph"              -> the static graph structure (information())
        #   "LLMGraph"           -> structure annotated with results (partial-safe)
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
        if prop in ("LLMGraph", "llmgraph"):
            # the static structure annotated with the computed results; only the
            # nodes whose dependencies were satisfied are assigned a result.
            evaluable = self._evaluable(data or {})
            info = self.information()
            info["Results"] = {n: final.get(n) for n in self.nodes if n in evaluable}
            info["Provided"] = dict(data or {})
            return info
        if isinstance(prop, str):
            if prop in self.node_names:
                return final.get(prop)
            raise ValueError(
                f"Unknown property {prop!r}: use None, 'All', 'Graph', 'LLMGraph', "
                f"a node name, or a list of node names. Nodes: {sorted(self.node_names)}"
            )
        if isinstance(prop, (list, tuple)):
            missing = [p for p in prop if p not in self.node_names]
            if missing:
                raise ValueError(
                    f"Not nodes: {missing}. Nodes: {sorted(self.node_names)}"
                )
            return {p: final.get(p) for p in prop}
        raise ValueError(
            f"Unknown property: {prop!r} (use None, 'All', 'Graph', 'LLMGraph', "
            f"a node name, or a list of node names)"
        )

    # -- introspection -----------------------------------------------------

    def _fn_repr(self, nd: Node) -> str:
        """Short representation of a node's evaluation function (for Information)."""
        if nd.kind in ("llm", "listable_llm"):
            return repr(nd.template)
        if nd.kind == "wolfram":
            return f"wolfram: {nd.code}"
        if nd.kind == "fn":
            return getattr(nd.fn, "__name__", "<callable>")
        return "?"

    def information(self, prop: Any = None) -> Any:
        """Static graph info, analogous to ``Information[LLMGraph[...]]``.

        ``prop`` mirrors Wolfram's ``Information`` properties:
          - ``None``          -> the full summary dict (default),
          - ``"Properties"``  -> the list of available properties,
          - ``"Nodes"``       -> per-node {Kind, Input, Function} (the Dataset),
          - ``"Graph"``       -> nodes + edges (the workflow graph),
          - ``"LLMEvaluator"``-> the graph-level LLMConfiguration defaults.
        """
        base = {
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
        if prop is None:
            return base
        if prop in ("Properties", "properties"):
            return ["Nodes", "Inputs", "Outputs", "Graph", "LLMEvaluator"]
        if prop in ("Graph", "graph"):
            return {
                "nodes": base["Nodes"], "edges": base["Edges"],
                "inputs": base["Inputs"], "outputs": base["Outputs"],
            }
        if prop in ("Nodes", "nodes"):
            return {
                n: {
                    "Kind": nd.kind,
                    "Input": nd.node_deps + nd.input_deps,
                    "Function": self._fn_repr(nd),
                }
                for n, nd in self.nodes.items()
            }
        if prop in ("LLMEvaluator", "llmevaluator"):
            return dict(self.llm_config)
        raise ValueError(
            f"Unknown Information property {prop!r}: use None, 'Properties', "
            f"'Nodes', 'Graph', or 'LLMEvaluator'"
        )

    def langgraph_structure(self) -> dict:
        """The *compiled* LangGraph for this graph — the actual execution graph
        (``__start__`` / ``__end__`` + fan-in edges) + LangGraph's Mermaid export.
        This is executor-specific (the LangGraph runtime layer); the semantic
        layer is :meth:`information`."""
        from .executors import LangGraphExecutor

        g = LangGraphExecutor().compile(self._make_plan()).get_graph()
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
