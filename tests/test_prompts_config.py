"""Counterpart implementations of Wolfram LLMFunction prompt specs + the
LLMConfiguration / Authentication / Information options. All offline.
"""

import pytest

from wolfram_llmgraph import LLMGraph, LLMPrompt, PromptLibrary, Slot, TemplateObject
from wolfram_llmgraph.backends import make_llm
from wolfram_llmgraph.prompts import normalize_prompt


class _Resp:
    def __init__(self, c):
        self.content = c


class _Cap:
    """A fake LLM that records the last prompt it was asked to render."""
    last = None

    def __init__(self, m):
        pass

    async def ainvoke(self, p):
        _Cap.last = p
        return _Resp("<" + p + ">")


def _fake():
    return lambda m: _Cap(m)


# -- prompt specs ---------------------------------------------------------

def test_list_of_strings_prompt():
    g = LLMGraph({"N": ["part one", "about `Topic`"]}, llm_factory=_fake())
    assert g.inputs == ["Topic"]                  # slot inferred after join
    assert g("spring") == "<part one\n\nabout spring>"


def test_llmprompt_builtin_library():
    g = LLMGraph({"S": {"llm_prompt": "Summarize"}}, llm_factory=_fake())
    assert g.inputs == ["Input"]                  # built-in Summarize uses `Input`


def test_llmprompt_custom_library_and_object():
    lib = PromptLibrary({"Greet": "Say hi to `Name`"})
    g = LLMGraph({"G": LLMPrompt("Greet")}, prompts=lib, llm_factory=_fake())
    assert g.inputs == ["Name"]
    assert g("Ada") == "<Say hi to Ada>"


def test_template_object_python_and_json():
    # Python object
    t = TemplateObject(("hello ", Slot("Who")))
    assert normalize_prompt(t) == "hello `Who`"
    # JSON form
    g = LLMGraph({"T": {"template_object": ["hello ", {"slot": "Who"}]}}, llm_factory=_fake())
    assert g.inputs == ["Who"]
    assert g("world") == "<hello world>"


def test_llmprompt_unknown_name_raises():
    with pytest.raises(KeyError):
        LLMGraph({"X": {"llm_prompt": "DoesNotExist"}}, llm_factory=_fake())


# -- LLMConfiguration -----------------------------------------------------

def test_node_config_parsed_and_merged():
    g = LLMGraph(
        {"A": {"prompt": "hi", "temperature": 0.1}},
        llm_config={"max_tokens": 50, "temperature": 0.9},
        llm_factory=_fake(),
    )
    assert g.nodes["A"].config == {"temperature": 0.1}
    # node overrides graph default
    assert g._node_config(g.nodes["A"]) == {"max_tokens": 50, "temperature": 0.1}


def test_system_prompt_prefixed():
    g = LLMGraph({"A": {"prompt": "hi `X`", "system": "You are terse."}}, llm_factory=_fake())
    g({"X": "there"})
    assert _Cap.last == "You are terse.\n\nhi there"


def test_make_llm_plumbs_config():
    llm = make_llm("anthropic", "claude-opus-4-8",
                   config={"temperature": 0.3, "max_tokens": 128}, api_key="sk-dummy")
    assert llm.temperature == 0.3
    assert llm.max_tokens == 128


# -- Authentication -------------------------------------------------------

def test_authentication_api_key_and_env(monkeypatch):
    g = LLMGraph({"A": "hi"}, authentication={"api_key": "sk-xyz"}, llm_factory=_fake())
    assert g._auth_key() == "sk-xyz"
    monkeypatch.setenv("MYKEY", "k123")
    g2 = LLMGraph({"A": "hi"}, authentication={"env": "MYKEY"}, llm_factory=_fake())
    assert g2._auth_key() == "k123"
    # Environment / None -> backend uses its own env lookup
    assert LLMGraph({"A": "hi"}, llm_factory=_fake())._auth_key() is None


# -- Information forms ----------------------------------------------------

def test_information_properties_and_nodes():
    g = LLMGraph({"P1": "a", "J": "pick `P1`"}, llm_config={"temperature": 0.2}, llm_factory=_fake())
    assert g.information("Properties") == ["Nodes", "Inputs", "Outputs", "Graph", "LLMEvaluator"]
    nodes = g.information("Nodes")
    assert nodes["J"]["Kind"] == "llm" and nodes["J"]["Input"] == ["P1"]
    assert g.information("LLMEvaluator") == {"temperature": 0.2}
    graph = g.information("Graph")
    assert set(graph["nodes"]) == {"P1", "J"} and ("P1", "J") in [tuple(e) for e in graph["edges"]]
    # default (no prop) is unchanged
    assert "NodeKinds" in g.information()
