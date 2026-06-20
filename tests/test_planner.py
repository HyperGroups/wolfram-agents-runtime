"""NL task → planned LLMGraph → result (the `wolfram_agents do` planner). Offline."""

import json

import pytest

from wolfram_llmgraph import plan_graph, run_task
from wolfram_llmgraph.planner import _extract_json, check_runnable, validate_ir

_IR = {
    "nodes": {
        "Pros": "list pros of `Topic`",
        "Cons": "list cons of `Topic`",
        "Final": "Given `Pros` and `Cons`, recommend.",
    },
    "output": ["Final"],
}


class _Resp:
    def __init__(self, c):
        self.content = c


def _fake():
    class _LLM:
        def __init__(self, m):
            pass

        async def ainvoke(self, p):
            if "You are a planner" in p:                 # the planning call
                return _Resp("```json\n" + json.dumps(_IR) + "\n```")
            return _Resp("<" + p.split("\n")[0][:20] + ">")  # echo a graph node

    return lambda m: _LLM(m)


# -- JSON extraction ------------------------------------------------------

def test_extract_json_from_fence_and_prose():
    assert _extract_json("```json\n{\"a\": 1}\n```") == {"a": 1}
    assert _extract_json("sure:\n{\"nodes\": {\"A\": \"x\"}} done")["nodes"] == {"A": "x"}
    with pytest.raises(ValueError):
        _extract_json("no json here")


# -- validation (security: LLM nodes only) --------------------------------

def test_validate_accepts_llm_nodes():
    validate_ir({"nodes": {"A": "do a", "B": {"prompt": "use `A`"}}})


@pytest.mark.parametrize("bad", [
    {"nodes": {"N": {"wolfram": "Run[\"rm -rf\"]"}}},   # would execute WL
    {"nodes": {"N": {"fn": "x"}}},                       # not an LLM node
    {"nodes": {"N": {"test": "x", "prompt": "y"}}},      # conditional/code
    {"nodes": {}},                                        # empty
    {"foo": 1},                                           # no nodes
])
def test_validate_rejects_code_and_malformed(bad):
    with pytest.raises(ValueError):
        validate_ir(bad)


# -- plan + run ------------------------------------------------------------

def test_plan_graph_returns_validated_ir():
    ir = plan_graph("recommend on a topic", llm_factory=_fake())
    assert set(ir["nodes"]) == {"Pros", "Cons", "Final"}
    assert ir["output"] == ["Final"]


def test_run_task_plans_then_executes():
    ir, result = run_task("recommend on a topic", llm_factory=_fake())
    assert set(ir["nodes"]) == {"Pros", "Cons", "Final"}
    # single output (Final) is unwrapped; it was rendered from Pros/Cons outputs
    assert isinstance(result, str) and result.startswith("<Given")


# -- runnability: cycles / bad outputs ------------------------------------

def test_check_runnable_rejects_cycle():
    with pytest.raises(ValueError, match="cycle"):
        check_runnable({"nodes": {"A": "use `B`", "B": "use `A`"}})


def test_check_runnable_rejects_unknown_output():
    with pytest.raises(ValueError):
        check_runnable({"nodes": {"A": "hi"}, "output": ["Nope"]})


# -- self-repair retry ----------------------------------------------------

def _sequenced(replies):
    """A fake whose successive ainvoke calls return ``replies`` in order."""
    state = {"i": 0}

    class _LLM:
        def __init__(self, m):
            pass

        async def ainvoke(self, p):
            i = min(state["i"], len(replies) - 1)
            state["i"] += 1
            return _Resp(replies[i])

    return lambda m: _LLM(m), state


def test_plan_graph_self_repairs_after_invalid_reply():
    good = json.dumps({"nodes": {"Final": "do it"}, "output": ["Final"]})
    factory, state = _sequenced([
        '{"nodes": {"X": {"wolfram": "1/0"}}}',   # 1st: disallowed code node -> retry
        good,                                      # 2nd: valid
    ])
    ir = plan_graph("a task", llm_factory=factory, retries=2)
    assert set(ir["nodes"]) == {"Final"}
    assert state["i"] == 2                          # it took exactly one retry


def test_plan_graph_raises_after_exhausting_retries():
    factory, _ = _sequenced(["not json at all"])    # always invalid
    with pytest.raises(ValueError, match="planner failed"):
        plan_graph("a task", llm_factory=factory, retries=1)
