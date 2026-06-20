"""The agents-first umbrella CLI + LLMSynthesize + doctor --fix. Offline."""

from wolfram_agents import cli as agentcli
from wolfram_llmgraph import LLMSynthesize, doctor


class _Resp:
    def __init__(self, c):
        self.content = c


def _fake():
    class _LLM:
        def __init__(self, m):
            pass

        async def ainvoke(self, p):
            return _Resp("OUT:" + p)

    return lambda m: _LLM(m)


# -- LLMSynthesize --------------------------------------------------------

def test_llmsynthesize_string_and_list():
    assert LLMSynthesize("hi", llm_factory=_fake()) == "OUT:hi"
    # a list prompt is normalized (joined with the prompt delimiter)
    assert LLMSynthesize(["a", "b"], llm_factory=_fake()) == "OUT:a\n\nb"


# -- agents CLI -----------------------------------------------------------

def test_agents_prompt_list_and_show(capsys):
    assert agentcli.main(["prompt", "list"]) == 0
    assert "Summarize" in capsys.readouterr().out
    assert agentcli.main(["prompt", "show", "Summarize"]) == 0
    assert "`Input`" in capsys.readouterr().out
    assert agentcli.main(["prompt", "show", "DoesNotExist"]) == 1


def test_agents_graph_passthrough(capsys):
    # `wolfram_agents graph info <file>` forwards to the llmgraph CLI
    assert agentcli.main(["graph", "info", "examples/renga.json"]) == 0
    assert "haiku" in capsys.readouterr().out


def test_agents_backends_lists_all(capsys):
    rc = agentcli.main(["backends"])
    out = capsys.readouterr().out
    assert "anthropic" in out and "claude-cli" in out and "auto ->" in out
    assert rc in (0, 1)  # depends on local credentials


# -- doctor --fix ---------------------------------------------------------

def test_doctor_fix_creates_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env.example").write_text("DASHSCOPE_API_KEY=\n", encoding="utf-8")
    rep = {"usable": False, "default_backend": None, "claude_cli": {"available": False}}
    actions = doctor.fix(rep, interactive=False)
    assert (tmp_path / ".env").exists()
    assert any("created .env" in a for a in actions)


def test_doctor_set_env_var_replaces_line(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("DASHSCOPE_API_KEY=\nOTHER=1\n", encoding="utf-8")
    doctor._set_env_var("DASHSCOPE_API_KEY", "sk-xyz")
    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "DASHSCOPE_API_KEY=sk-xyz" in content and "OTHER=1" in content
