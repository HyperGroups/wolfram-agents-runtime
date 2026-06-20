"""LLMGraphSubmit — asynchronous evaluation with handler-function events.
Offline (fake LLM). Mirrors the Wolfram LLMGraphSubmit reference page.
"""

from wolfram_llmgraph import LLMGraph, LLMGraphSubmit, Task, task_wait


class _Resp:
    def __init__(self, c):
        self.content = c


def _fake():
    class _LLM:
        def __init__(self, m):
            pass

        async def ainvoke(self, p):
            return _Resp("<" + p + ">")

    return lambda m: _LLM(m)


def _graph():
    return LLMGraph(
        {"haiku": "haiku about `Topic`", "complete": "extend `haiku`"},
        llm_factory=_fake(),
    )


def test_submit_basic_events_and_result():
    events, final = [], {}
    t = _graph().submit(
        {"Topic": "spring"},
        handlers={
            "NodeSubmitted": lambda e: events.append(("sub", e["CurrentNode"])),
            "NodeSynthesized": lambda e: events.append(("syn", e["CurrentNode"])),
            "TaskFinished": lambda e: final.update(e["GraphResults"]),
        },
    )
    assert isinstance(t, Task)
    t.wait()
    assert t.status == "Removed"                       # full task lifecycle ran
    assert ("sub", "haiku") in events and ("syn", "haiku") in events
    assert ("syn", "complete") in events
    # GraphResults is a per-target association; result() unwraps a single output
    assert set(final) == {"complete"}
    assert t.result() == "<extend <haiku about spring>>"


def test_submit_target_all_and_subset():
    t = _graph().submit({"Topic": "autumn"}, "All").wait()
    assert set(t.graph_results()) == {"Topic", "haiku", "complete"}
    t2 = _graph().submit({"Topic": "x"}, ["haiku"]).wait()
    assert set(t2.graph_results()) == {"haiku"}


def test_submit_node_canceled_event():
    seen = []
    g = LLMGraph(
        {"C": {"fn": (lambda: "x"), "test": (lambda K: K > 5), "test_input": ["K"]}},
        llm_factory=_fake(),
    )
    g.submit({"K": 1}, handlers={"NodeCanceled": lambda e: seen.append(e["CurrentNode"])}).wait()
    assert seen == ["C"]


def test_submit_node_failed_event():
    seen = []

    def boom():
        raise ValueError("boom")

    g = LLMGraph({"A": boom}, llm_factory=_fake())
    g.submit({}, handlers={"NodeFailed": lambda e: seen.append(e["CurrentNode"])}).wait()
    assert seen == ["A"]


def test_submit_handler_keys_subset_and_taskwait_fn():
    statuses = []
    t = LLMGraphSubmit(
        _graph(), {"Topic": "winter"},
        handlers={"TaskStatusChanged": lambda e: statuses.append(e)},
        handler_keys="TaskStatus",
    )
    task_wait(t)
    # each handler assoc contains only the requested key
    assert all(set(s) == {"TaskStatus"} for s in statuses)
    assert {"Running", "Finished", "Removed"} <= {s["TaskStatus"] for s in statuses}


def test_submit_handler_keys_all_has_every_key():
    captured = {}
    LLMGraphSubmit(
        _graph(), {"Topic": "x"},
        handlers={"TaskFinished": lambda e: captured.update(e)},
        handler_keys="All",
    ).wait()
    for k in ("EventName", "GraphResults", "Task", "TaskStatus", "LLMGraph"):
        assert k in captured
