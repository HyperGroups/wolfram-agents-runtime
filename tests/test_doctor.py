"""The `llmgraph doctor` environment self-check. Offline."""

from wolfram_llmgraph.backends import BACKENDS
from wolfram_llmgraph.doctor import diagnose, format_report


def test_diagnose_shape_and_backends():
    rep = diagnose()
    for key in ("python", "deps_installed", "default_backend", "usable",
                "backends", "claude_cli", "wolframscript"):
        assert key in rep
    names = {b["name"] for b in rep["backends"]}
    assert names == set(BACKENDS)
    # every backend entry carries availability + a remediation hint when missing
    for b in rep["backends"]:
        assert set(b) == {"name", "available", "detail", "hint"}
        if not b["available"]:
            assert b["hint"]


def test_diagnose_detects_qwen_from_env(monkeypatch):
    # clear all known keys, then set only DASHSCOPE -> qwen becomes available
    for v in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DASHSCOPE_API_KEY",
              "QWEN_API_KEY", "DEEPSEEK_API_KEY", "DASHSCOPE_TOKENPLAN_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    rep = diagnose()
    qwen = next(b for b in rep["backends"] if b["name"] == "qwen")
    assert qwen["available"] is True
    assert rep["usable"] is True


def test_format_report_is_text():
    out = format_report(diagnose())
    assert "llmgraph doctor" in out
    assert "LLM backends" in out
