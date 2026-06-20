"""The Executor port: the semantic core runs identically on the zero-dep
ReferenceExecutor and the LangGraphExecutor. This is the architectural contract
test — it proves the Wolfram-compatible semantics are a true *subset* that needs
no LangGraph, and that LangGraph is a swappable adapter.
"""

import pytest

from wolfram_llmgraph import FailedNode, LLMGraph, is_canceled, is_failed
from wolfram_llmgraph.executors import (
    LangGraphExecutor,
    ReferenceExecutor,
    get_executor,
)

EXECUTORS = ["langgraph", "reference"]


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


def _graph(executor):
    # fan-out/fan-in + conditional (canceled) + listable, all offline
    return LLMGraph(
        {
            "A": {"fn": (lambda: 2)},
            "B": (lambda A: A * 10),
            "C": (lambda A: A + 1),
            "J": (lambda B, C: B + C),                # fan-in of two parents
            "Cond": {"fn": (lambda: "ran"),
                     "test": (lambda A: A > 100), "test_input": ["A"]},  # canceled
            "M": {"listable_llm": "spell `X`", "input": ["X"]},          # listable
        },
        executor=executor,
        llm_factory=_fake(),
    )


def _norm(d):
    return {k: (str(v) if is_canceled(v) or is_failed(v) else v) for k, v in d.items()}


@pytest.mark.parametrize("executor", EXECUTORS)
def test_semantics_identical_on_each_executor(executor):
    out = _graph(executor)({"X": ["1", "2", "3"]}, "All")
    assert out["A"] == 2
    assert out["B"] == 20 and out["C"] == 3
    assert out["J"] == 23                              # fan-in concurrency + dependency
    assert is_canceled(out["Cond"])                    # test false -> canceled
    assert out["M"] == ["<spell 1>", "<spell 2>", "<spell 3>"]   # listable map


def test_reference_and_langgraph_agree():
    inp = {"X": ["a", "b"]}
    lg = _norm(_graph("langgraph")(inp, "All"))
    ref = _norm(_graph("reference")(inp, "All"))
    assert lg == ref                                   # the contract oracle


@pytest.mark.parametrize("executor", EXECUTORS)
def test_override_bypasses_node_on_each_executor(executor):
    out = _graph(executor)({"X": ["z"], "B": 999}, "All")
    assert out["B"] == 999                             # provided value used, node skipped
    assert out["J"] == 999 + 3                         # downstream sees the override


@pytest.mark.parametrize("executor", EXECUTORS)
def test_failure_propagates_on_each_executor(executor):
    g = LLMGraph(
        {"A": "x", "D": {"fn": (lambda A: f"got {A}")}, "OK": {"fn": (lambda: 7)}},
        executor=executor, llm_factory=_fake(),
    )
    # seed a FailedNode via override -> D (depends on A) propagates; OK unaffected
    out = g({"A": FailedNode("A", "seed")}, "All")
    assert is_failed(out["D"])
    assert out["OK"] == 7


def test_get_executor_resolution(monkeypatch):
    assert isinstance(get_executor("reference"), ReferenceExecutor)
    assert isinstance(get_executor("langgraph"), LangGraphExecutor)
    inst = ReferenceExecutor()
    assert get_executor(inst) is inst                  # instance passthrough
    monkeypatch.setenv("LLMGRAPH_EXECUTOR", "reference")
    assert isinstance(get_executor(None), ReferenceExecutor)   # env default
    with pytest.raises(ValueError):
        get_executor("nope")
