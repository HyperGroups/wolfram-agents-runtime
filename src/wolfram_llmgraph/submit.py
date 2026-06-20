"""Asynchronous LLMGraph evaluation — counterpart to Wolfram ``LLMGraphSubmit``.

``LLMGraphSubmit(graph, input, target)`` schedules the graph on a background
thread and returns a :class:`Task` (our ``TaskObject`` counterpart). While it
runs it fires ``HandlerFunctions`` on events, mirroring Wolfram's event model:

* graph events — ``NodeSubmitted`` / ``NodeSynthesized`` / ``NodeCanceled`` /
  ``NodeFailed`` / ``ResultGenerated``
* task events  — ``TaskStarted`` / ``TaskStatusChanged`` / ``TaskFinished`` /
  ``TaskRemoved`` / ``FailureOccurred``

This is a **separate module** because ``LLMGraphSubmit`` is its own Wolfram
function (its own reference page) — and the runtime already has the event feed it
needs: it drives a :class:`~wolfram_llmgraph.RunMonitor` and translates its node
lifecycle events into LLMGraphSubmit events.

    task = LLMGraphSubmit(graph, {"Topic": "spring"},
                          handlers={"TaskFinished": lambda e: print(e["GraphResults"])})
    task.wait()            # TaskWait
    task.result()          # GraphResults for the requested target

Handlers receive an association whose keys are chosen by ``handler_keys``
(Wolfram's ``HandlerFunctionsKeys``): ``EventName`` / ``Failure`` / ``CurrentNode``
/ ``NodeResult`` / ``LLMGraph`` / ``GraphResults`` / ``Task`` / ``TaskStatus``.
Unavailable values are ``Missing[NotAvailable]``. Note: streamed ``NodeResult`` is
the node's (truncated) preview; the exact values are in ``GraphResults`` / ``result()``.

One submission at a time per graph instance (it borrows the graph's monitor slot).
"""

from __future__ import annotations

import threading
import uuid as _uuid
from queue import Empty
from typing import Any, Callable

from .monitor import RunMonitor

MISSING_NA = "Missing[NotAvailable]"
MISSING_NAPP = "Missing[NotApplicable]"

# event names (Wolfram LLMGraphSubmit)
NODE_SUBMITTED = "NodeSubmitted"
NODE_SYNTHESIZED = "NodeSynthesized"
NODE_CANCELED = "NodeCanceled"
NODE_FAILED = "NodeFailed"
RESULT_GENERATED = "ResultGenerated"
TASK_STARTED = "TaskStarted"
TASK_STATUS_CHANGED = "TaskStatusChanged"
TASK_FINISHED = "TaskFinished"
TASK_REMOVED = "TaskRemoved"
FAILURE_OCCURRED = "FailureOccurred"

ALL_KEYS = [
    "EventName", "Failure", "CurrentNode", "NodeResult",
    "LLMGraph", "GraphResults", "Task", "TaskStatus",
]


def _target_to_prop(target: Any) -> Any:
    if target in (None, "Automatic", "auto", "automatic"):
        return None
    if target in ("All", "all"):
        return "All"
    if isinstance(target, (list, tuple)):
        return list(target)
    return target  # a single node name


class Task:
    """A running asynchronous LLMGraph evaluation — our ``TaskObject``."""

    def __init__(self, graph, input, target="Automatic", *,
                 handlers=None, handler_keys="Automatic"):
        self.uuid = _uuid.uuid4().hex
        self.graph = graph
        self.input = input
        self.target = target
        self.prop = _target_to_prop(target)
        self.handlers = handlers
        self.handler_keys = handler_keys
        self.status = "Created"
        self._results_all: dict | None = None
        self._failure: str | None = None
        self._done = threading.Event()

        self._monitor = RunMonitor()
        self._prev_monitor = getattr(graph, "monitor", None)
        self._q = self._monitor.subscribe()
        self._consumer = threading.Thread(target=self._consume, daemon=True)
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._consumer.start()
        self._worker.start()

    # -- handler dispatch --------------------------------------------------

    def _handler_for(self, event: str) -> Callable | None:
        h = self.handlers
        if h is None:
            return None
        if callable(h):
            return h                       # one function for every event
        if isinstance(h, dict):
            return h.get(event)            # per-event mapping
        return None

    def _assoc(self, event, *, node=None, node_result=None,
               failure=None, graph_results=None, task_status=None) -> dict:
        full = {
            "EventName": event,
            "Failure": failure if failure is not None else MISSING_NA,
            "CurrentNode": node if node is not None else MISSING_NAPP,
            "NodeResult": node_result if node_result is not None else MISSING_NA,
            "LLMGraph": self.graph,
            "GraphResults": graph_results if graph_results is not None else MISSING_NA,
            "Task": self,
            "TaskStatus": task_status if task_status is not None else self.status,
        }
        keys = self.handler_keys
        if keys in (None, "Automatic", "automatic", "All", "all"):
            return full
        if isinstance(keys, str):
            return {keys: full.get(keys, MISSING_NA)}
        if isinstance(keys, (list, tuple)):
            return {k: full.get(k, MISSING_NA) for k in keys}
        return full

    def _fire(self, event, **kw):
        fn = self._handler_for(event)
        if fn is None:
            return
        try:
            fn(self._assoc(event, **kw))
        except Exception:  # a handler error must not break the task
            pass

    # -- event consumer (separate thread) ----------------------------------

    def _consume(self):
        while True:
            try:
                ev = self._q.get(timeout=30)
            except Empty:
                if self._done.is_set():
                    break
                continue
            t = ev.get("type")
            if t == "run_start":
                self.status = "Running"
                self._fire(TASK_STARTED, task_status="Running")
                self._fire(TASK_STATUS_CHANGED, task_status="Running")
            elif t == "node":
                rec = ev["node"]
                name, st = rec["name"], rec["status"]
                if st == "running":
                    self._fire(NODE_SUBMITTED, node=name)
                elif st == "done":
                    self._fire(NODE_SYNTHESIZED, node=name, node_result=rec.get("preview"))
                elif st == "canceled":
                    self._fire(NODE_CANCELED, node=name)
                elif st == "error":
                    self._fire(NODE_FAILED, node=name,
                               failure=rec.get("error") or rec.get("preview"))
            elif t == "run_end":
                self._done.wait(10)        # let the worker store the results
                gr = self._graph_results()
                self._fire(RESULT_GENERATED, graph_results=gr)
                self.status = "Finished"
                self._fire(TASK_FINISHED, task_status="Finished", graph_results=gr)
                self._fire(TASK_STATUS_CHANGED, task_status="Finished")
                self.status = "Removed"
                self._fire(TASK_REMOVED, task_status="Removed")
                self._fire(TASK_STATUS_CHANGED, task_status="Removed")
                break
        self._monitor.unsubscribe(self._q)

    # -- worker (runs the graph) -------------------------------------------

    def _run(self):
        self.graph.monitor = self._monitor
        try:
            self._results_all = self.graph(self.input, "All")
        except Exception as exc:  # noqa: BLE001
            self._failure = repr(exc)
            self._fire(FAILURE_OCCURRED, failure=self._failure)
        finally:
            self.graph.monitor = self._prev_monitor
            self._done.set()

    # -- public API (TaskObject) -------------------------------------------

    def wait(self, timeout: float | None = None) -> "Task":
        """Block until the task finishes (Wolfram ``TaskWait``)."""
        self._worker.join(timeout)
        self._consumer.join(timeout)
        return self

    def _graph_results(self) -> dict:
        """The per-target results **association** (Wolfram ``"GraphResults"`` key)."""
        all_res = self._results_all
        if all_res is None:
            return {}
        if self.prop is None:
            return {n: all_res.get(n) for n in self.graph.outputs}
        if self.prop == "All":
            return dict(all_res)
        if isinstance(self.prop, list):
            return {n: all_res.get(n) for n in self.prop}
        return {self.prop: all_res.get(self.prop)}

    def result(self) -> Any:
        """Convenience result for the target — a single output node is unwrapped
        (like ``LLMGraph[...][input]``); otherwise the per-target association."""
        if self._results_all is None:
            return MISSING_NA
        gr = self._graph_results()
        if self.prop is None and len(gr) == 1:
            return next(iter(gr.values()))
        return gr

    def graph_results(self) -> dict:
        """The per-target results association (the ``"GraphResults"`` key)."""
        return self._graph_results()

    @property
    def failure(self) -> str | None:
        return self._failure

    def __repr__(self) -> str:
        return f"Task[{self.uuid[:8]}··{self.status}]"


def LLMGraphSubmit(graph, input=None, target="Automatic", *,
                   handlers=None, handler_keys="Automatic") -> Task:
    """Schedule an asynchronous LLMGraph evaluation; return a :class:`Task`.

    ``target`` selects what ``result()`` returns: ``"Automatic"`` (output nodes),
    ``"All"``, a node name, or a list of node names. ``handlers`` is one callable
    (every event) or a ``{event_name: callable}`` mapping; ``handler_keys`` picks
    which keys land in each handler's association.
    """
    return Task(graph, input, target, handlers=handlers, handler_keys=handler_keys)


def task_wait(task: Task, timeout: float | None = None) -> Task:
    """Wolfram ``TaskWait`` — block until ``task`` finishes."""
    return task.wait(timeout)
