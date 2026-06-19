"""Offline tests — no network. A fake LLM stands in for ChatAnthropic so we
can verify dependency inference, scheduling, fan-in, and result selection.
"""

import asyncio
import time

import pytest

from wolfram_llmgraph import LLMGraph, is_canceled


class FakeLLM:
    """Echoes the rendered prompt; records wall-clock start time per call."""

    def __init__(self, model, log=None, delay=0.0):
        self.model = model
        self.log = log
        self.delay = delay

    async def ainvoke(self, prompt):
        if self.log is not None:
            self.log.append((self.model, time.perf_counter()))
        if self.delay:
            await asyncio.sleep(self.delay)

        class _Resp:
            content = f"[{self.model}] {prompt}"

        return _Resp()


def fake_factory(log=None, delay=0.0):
    return lambda model: FakeLLM(model, log=log, delay=delay)


def test_dependency_inference_from_slots():
    g = LLMGraph(
        {
            "Poet1": "a poem",
            "Judge": "pick the best: `Poet1`",
        },
        llm_factory=fake_factory(),
    )
    assert g.nodes["Judge"].node_deps == ["Poet1"]
    assert g.outputs == ["Judge"]
    assert g.inputs == []


def test_input_argument_classification():
    g = LLMGraph({"haiku": "haiku about `Topic`."}, llm_factory=fake_factory())
    assert g.inputs == ["Topic"]
    assert g.nodes["haiku"].input_deps == ["Topic"]
    assert g.nodes["haiku"].node_deps == []


def test_single_output_unwrapped():
    g = LLMGraph({"a": "hi", "b": "use `a`"}, llm_factory=fake_factory())
    out = g()
    assert isinstance(out, str)
    assert "use [" in out  # b rendered with a's content substituted in


def test_all_property_returns_every_node():
    g = LLMGraph({"a": "hi", "b": "use `a`"}, llm_factory=fake_factory())
    out = g({}, "All")
    assert set(out) >= {"a", "b"}


def test_code_node_and_mixed_graph():
    def double(x):
        return x * 2

    g = LLMGraph(
        {
            "x": {"fn": (lambda: 21)},
            "double": double,
        },
        llm_factory=fake_factory(),
    )
    # 'double' takes parameter 'x' -> depends on node 'x'
    assert g.nodes["double"].node_deps == ["x"]
    assert g({}, "All")["double"] == 42


def test_intermediate_override_bypasses_node():
    g = LLMGraph({"a": "hi", "b": "use `a`"}, llm_factory=fake_factory())
    out = g({"a": "OVERRIDE"}, "All")
    assert out["a"] == "OVERRIDE"
    assert "OVERRIDE" in out["b"]


def test_wolfram_node_parse_and_deps():
    g = LLMGraph(
        {
            "haiku": "about `Topic`",
            "chars": {"wolfram": 'StringLength[deps["haiku"]]'},
        },
        llm_factory=fake_factory(),
    )
    assert g.nodes["chars"].kind == "wolfram"
    assert g.nodes["chars"].code == 'StringLength[deps["haiku"]]'
    assert g.nodes["chars"].node_deps == ["haiku"]  # auto-detected from deps[...]
    assert g.outputs == ["chars"]


def test_wolfram_node_explicit_input():
    g = LLMGraph(
        {
            "a": "hi",
            "w": {"wolfram": "Length[x]", "input": ["a"]},
        },
        llm_factory=fake_factory(),
    )
    assert g.nodes["w"].kind == "wolfram"
    assert g.nodes["w"].node_deps == ["a"]


def test_select_single_node_by_name():
    g = LLMGraph({"a": "hi", "b": "use `a`"}, llm_factory=fake_factory())
    out = g({}, "a")
    assert isinstance(out, str)
    assert out == "[None] hi"  # node 'a' only, unwrapped


def test_select_list_of_nodes():
    g = LLMGraph(
        {"a": "hi", "b": "use `a`", "c": "use `a`"},
        llm_factory=fake_factory(),
    )
    out = g({}, ["a", "b"])
    assert set(out) == {"a", "b"}  # exactly the requested nodes, no 'c'


def test_select_graph_structure():
    g = LLMGraph({"a": "hi", "b": "use `a`"}, llm_factory=fake_factory())
    info = g({}, "Graph")
    assert info["Nodes"] == ["a", "b"]
    assert ("a", "b") in info["Edges"]


def test_select_unknown_node_raises():
    g = LLMGraph({"a": "hi"}, llm_factory=fake_factory())
    with pytest.raises(ValueError):
        g({}, "nope")
    with pytest.raises(ValueError):
        g({}, ["a", "nope"])


def test_conditional_node_runs_when_test_true():
    g = LLMGraph(
        {
            "Cond": {
                "fn": (lambda: "NodeHasRun"),
                "test": (lambda NodeControl: bool(NodeControl)),
                "test_input": ["NodeControl"],
            }
        },
        llm_factory=fake_factory(),
    )
    # test inputs become graph inputs even though the eval fn ignores them
    assert g.inputs == ["NodeControl"]
    out = g({"NodeControl": True}, "All")
    assert out["Cond"] == "NodeHasRun"
    assert not is_canceled(out["Cond"])


def test_conditional_node_canceled_when_test_false():
    g = LLMGraph(
        {
            "Cond": {
                "fn": (lambda: "NodeHasRun"),
                "test": (lambda NodeControl: bool(NodeControl)),
                "test_input": ["NodeControl"],
            }
        },
        llm_factory=fake_factory(),
    )
    out = g({"NodeControl": False}, "All")
    assert is_canceled(out["Cond"])  # still present, carrying the sentinel
    assert str(out["Cond"]) == "Missing[CanceledNode, Cond]"


def test_conditional_test_input_creates_edge_to_parent():
    # a test that reads another node's output makes that node a parent (edge)
    g = LLMGraph(
        {
            "Gate": {"fn": (lambda: True)},
            "Cond": {
                "fn": (lambda: "ran"),
                "test": (lambda Gate: bool(Gate)),
                "test_input": ["Gate"],
            },
        },
        llm_factory=fake_factory(),
    )
    assert g.nodes["Cond"].node_deps == ["Gate"]
    assert ("Gate", "Cond") in g.information()["Edges"]
    assert g({}, "All")["Cond"] == "ran"


def test_independent_nodes_run_concurrently():
    log = []
    g = LLMGraph(
        {
            "A": "first",
            "B": "second",
            "J": "combine `A` and `B`",
        },
        llm_factory=fake_factory(log=log, delay=0.2),
    )
    start = time.perf_counter()
    g()
    elapsed = time.perf_counter() - start
    # A and B are independent: concurrent => well under the serial 0.6s.
    assert elapsed < 0.5, f"expected concurrency, took {elapsed:.2f}s"


# -- P0-1: ListableLLMFunction tests --

def test_listable_llm_parsing():
    from wolfram_llmgraph import parse_node
    nd = parse_node("T", {
        "listable_llm": "translate `words` to French",
        "input": ["words"],
    })
    assert nd.kind == "listable_llm"
    assert nd.list_inputs == ["words"]
    assert nd.deps == ["words"]


def test_listable_llm_execution():
    g = LLMGraph(
        {"T": {"listable_llm": "translate `words` to French", "input": ["words"]}},
        llm_factory=fake_factory(),
    )
    result = g({"words": ["hello", "world", "spring"]})
    assert isinstance(result, list)
    assert len(result) == 3
    assert "hello" in result[0]
    assert "world" in result[1]
    assert "spring" in result[2]


def test_listable_llm_multiple_lists():
    g = LLMGraph(
        {"T": {"listable_llm": "combine `a` and `b`", "input": ["a", "b"]}},
        llm_factory=fake_factory(),
    )
    result = g({"a": ["x", "y"], "b": ["1", "2"]})
    assert len(result) == 2
    assert "x" in result[0] and "1" in result[0]
    assert "y" in result[1] and "2" in result[1]


def test_listable_llm_mismatched_lengths():
    g = LLMGraph(
        {"T": {"listable_llm": "combine `a` and `b`", "input": ["a", "b"]}},
        llm_factory=fake_factory(),
    )
    with pytest.raises(ValueError, match="mismatched lengths"):
        g({"a": ["x", "y"], "b": ["1"]})


# -- P0-2: Failure propagation tests --

def test_failed_node_sentinel():
    from wolfram_llmgraph import FailedNode, is_failed, is_propagated
    f = FailedNode("X", "test error")
    assert is_failed(f)
    assert is_propagated(f)
    assert "Failed" in repr(f)
    assert "test error" in repr(f)


def test_canceled_node_propagates_downstream():
    """A node depending on a CanceledNode should also be CanceledNode."""
    g = LLMGraph(
        {
            "A": {"fn": lambda: "ok"},
            "B": {"fn": lambda A: "skip", "test": lambda: False},
            "C": {"fn": lambda B: f"got {B}"},
        },
        llm_factory=fake_factory(),
    )
    result = g({}, "All")
    from wolfram_llmgraph import is_canceled
    assert is_canceled(result["B"])
    assert is_canceled(result["C"])


def test_failed_wolfram_propagates():
    """A wolfram node that fails should produce FailedNode, propagating downstream."""
    g = LLMGraph(
        {
            "Fail": {"wolfram": "1/0", "input": []},
            "Down": {"fn": lambda Fail: f"got {Fail}"},
        },
        llm_factory=fake_factory(),
    )
    result = g({}, "All")
    from wolfram_llmgraph import is_failed
    assert is_failed(result["Fail"])
    assert is_failed(result["Down"])


def test_failed_node_does_not_break_independent_branches():
    """Failure in one branch should not affect independent branches."""
    g = LLMGraph(
        {
            "Fail": {"wolfram": "1/0", "input": []},
            "OK": {"fn": lambda: 42},
        },
        llm_factory=fake_factory(),
    )
    result = g({}, "All")
    from wolfram_llmgraph import is_failed
    assert is_failed(result["Fail"])
    assert result["OK"] == 42
