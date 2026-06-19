"""Offline tests for the runtime observability layer (RunMonitor).

No network/kernel: code + conditional nodes, plus a fake LLM, exercise every
node status (done / canceled / skipped / error) and the streamed event feed.
"""

import pytest

from wolfram_llmgraph import LLMGraph, RunMonitor


def _fake_factory():
    class _Resp:
        def __init__(self, c):
            self.content = c

    class _LLM:
        def __init__(self, model):
            self.model = model

        async def ainvoke(self, prompt):
            return _Resp(f"[{self.model}] {prompt}")

    return lambda model: _LLM(model)


def test_monitor_tracks_node_statuses():
    mon = RunMonitor()
    g = LLMGraph(
        {
            "A": {"fn": (lambda: 21)},
            "B": (lambda A: A * 2),                      # 42
            "Cond": {                                     # canceled (test false)
                "fn": (lambda: "ran"),
                "test": (lambda A: A > 100),
                "test_input": ["A"],
            },
        },
        monitor=mon,
        llm_factory=_fake_factory(),
    )
    out = g({}, "All")
    assert out["B"] == 42

    snap = mon.snapshot()
    assert snap["status"] == "done"
    assert snap["progress"] == {"done": 3, "total": 3}
    assert snap["nodes"]["A"]["status"] == "done"
    assert snap["nodes"]["B"]["status"] == "done"
    assert snap["nodes"]["B"]["preview"] == "42"
    assert snap["nodes"]["Cond"]["status"] == "canceled"
    # durations recorded for nodes that actually ran
    assert snap["nodes"]["B"]["duration"] is not None


def test_monitor_marks_overridden_node_skipped():
    mon = RunMonitor()
    g = LLMGraph({"a": (lambda: 1), "b": (lambda a: a + 1)},
                 monitor=mon, llm_factory=_fake_factory())
    g({"a": 99}, "All")
    snap = mon.snapshot()
    assert snap["nodes"]["a"]["status"] == "skipped"
    assert snap["nodes"]["b"]["status"] == "done"


def test_monitor_streams_events_to_subscriber():
    mon = RunMonitor()
    q = mon.subscribe()
    g = LLMGraph({"a": (lambda: 1)}, monitor=mon, llm_factory=_fake_factory())
    g({}, "All")
    kinds = []
    while not q.empty():
        kinds.append(q.get_nowait()["type"])
    assert kinds[0] == "run_start"
    assert kinds[-1] == "run_end"
    assert "node" in kinds


def test_monitor_records_error_status():
    mon = RunMonitor()

    def boom():
        raise ValueError("kaboom")

    g = LLMGraph({"x": boom}, monitor=mon, llm_factory=_fake_factory())
    with pytest.raises(Exception):
        g({}, "All")
    snap = mon.snapshot()
    assert snap["status"] == "error"
    assert snap["nodes"]["x"]["status"] == "error"
    assert "kaboom" in snap["nodes"]["x"]["error"]


def test_monitor_streaming_event():
    """Test that node_streaming emits streaming events."""
    mon = RunMonitor()
    mon.start_run("test-run", {"Nodes": ["A"], "NodeKinds": {"A": "llm"}, "Edges": [], "Inputs": [], "Outputs": ["A"]}, {})
    mon.node_running("test-run", "A")
    mon.node_streaming("test-run", "A", "Hello ")
    mon.node_streaming("test-run", "A", "World")
    
    snap = mon.snapshot()
    assert snap["nodes"]["A"]["preview"] == "Hello World"
    
    q = mon.subscribe()
    mon.node_streaming("test-run", "A", "!")
    event = q.get_nowait()
    assert event["type"] == "node_stream"
    assert event["node"] == "A"
    assert event["chunk"] == "!"


def test_monitor_cost_calculation():
    """Test that cost is calculated when model and usage are available."""
    mon = RunMonitor()
    mon.start_run("test-run", {"Nodes": ["A"], "NodeKinds": {"A": "llm"}, "Edges": [], "Inputs": [], "Outputs": ["A"]}, {})
    mon.node_running("test-run", "A")
    mon.note_model("test-run", "A", "claude-opus-4-8")
    mon.note_usage("test-run", "A", {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150})
    mon.node_finished("test-run", "A", "result")
    
    snap = mon.snapshot()
    assert "cost" in snap
    assert snap["cost"]["total_usd"] > 0
    assert "A" in snap["cost"]["nodes"]
    assert snap["cost"]["nodes"]["A"]["model"] == "claude-opus-4-8"
