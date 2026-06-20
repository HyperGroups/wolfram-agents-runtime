"""Bare single-value input — Wolfram's ``g[val]`` form (e.g. ``poem["winter"]``,
``parallel[{"1","2","3"}]``) where a non-association value feeds the lone input.
"""

import pytest

from wolfram_llmgraph import LLMGraph


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


def test_bare_value_for_single_input():
    g = LLMGraph({"Haiku": "haiku about `Topic`"}, llm_factory=_fake())
    assert g("winter") == "<haiku about winter>"
    # equivalent to the dict form
    assert g({"Topic": "winter"}) == "<haiku about winter>"


def test_bare_list_for_single_listable_input():
    g = LLMGraph({"M": {"listable_llm": "spell `X`", "input": ["X"]}}, llm_factory=_fake())
    assert g(["1", "2"]) == ["<spell 1>", "<spell 2>"]


def test_bare_value_rejected_when_multiple_inputs():
    g = LLMGraph({"J": "use `A` and `B`"}, llm_factory=_fake())
    with pytest.raises(ValueError):
        g("x")
