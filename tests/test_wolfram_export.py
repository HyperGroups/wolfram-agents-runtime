"""IR -> Wolfram `LLMGraph` round-trip export, and `do` persisting it. Offline."""

import json

from wolfram_llmgraph import save_graph, slugify, to_wolfram
from wolfram_agents import cli as agentcli

_IR = {
    "nodes": {
        "haiku": "generate a haiku about `Topic`.",
        "complete": "add an extra stanza to the hokku `haiku` to make it a renga.",
    },
    "output": ["complete"],
}


# -- to_wolfram -----------------------------------------------------------

def test_to_wolfram_matches_native_spec_shape():
    wl = to_wolfram(_IR, task="write a renga")
    assert "spec = <|" in wl
    assert 'graph = LLMGraph[spec];' in wl
    # backtick slots carry over verbatim (lossless for string-LLM nodes)
    assert '"haiku" -> "generate a haiku about `Topic`."' in wl
    assert "to make it a renga." in wl
    assert "runtime-declared output nodes: complete" in wl


def test_to_wolfram_escapes_quotes_and_newlines():
    wl = to_wolfram({"nodes": {"N": 'say "hi"\nthen bye'}})
    assert '\\"hi\\"' in wl       # double quotes escaped
    assert "\\nthen bye" in wl    # newline escaped, stays on one line


def test_to_wolfram_dict_node_with_input_uses_assoc_form():
    wl = to_wolfram({"nodes": {"T": {"prompt": "use `a`", "input": ["a"]}}})
    assert '"Prompt" -> "use `a`"' in wl
    assert '"Input" -> {"a"}' in wl


def test_to_wolfram_rejects_non_llm_node():
    import pytest
    with pytest.raises(ValueError):
        to_wolfram({"nodes": {"X": {"wolfram": "1/0"}}})


# -- save_graph + slugify -------------------------------------------------

def test_save_graph_writes_json_and_wls(tmp_path):
    base = str(tmp_path / "out" / "renga")
    paths = save_graph(_IR, base, task="write a renga")
    assert paths["json"].endswith(".json") and paths["wls"].endswith(".wls")
    loaded = json.loads(open(paths["json"], encoding="utf-8").read())
    assert loaded == _IR
    assert "LLMGraph[spec]" in open(paths["wls"], encoding="utf-8").read()


def test_slugify():
    assert slugify("Write a two-line tea-shop motto!") == "write-a-two-line-tea-shop-motto"
    assert slugify("   ") == "graph"


# -- `do` persists the planned graph by default ---------------------------

def test_do_saves_graph_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("wolfram_llmgraph.planner.run_task",
                        lambda *a, **k: (_IR, "RESULT"))
    monkeypatch.setattr("wolfram_llmgraph.backends.resolve_backend",
                        lambda *a, **k: "claude-cli")
    rc = agentcli.main(["do", "write a renga"])
    assert rc == 0
    saved = tmp_path / "graphs" / "write-a-renga.json"
    assert saved.exists()
    assert (tmp_path / "graphs" / "write-a-renga.wls").exists()
    assert json.loads(saved.read_text(encoding="utf-8")) == _IR


def test_do_no_save_skips_persistence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("wolfram_llmgraph.planner.run_task",
                        lambda *a, **k: (_IR, "RESULT"))
    monkeypatch.setattr("wolfram_llmgraph.backends.resolve_backend",
                        lambda *a, **k: "claude-cli")
    rc = agentcli.main(["do", "write a renga", "--no-save"])
    assert rc == 0
    assert not (tmp_path / "graphs").exists()
