"""Tests for backend functionality: pricing, cost estimation, auto-detection."""

import os
import pytest

from wolfram_llmgraph.backends import (
    MODEL_PRICING,
    estimate_cost,
    detect_available_backend,
    validate_backend,
    resolve_backend,
)


class TestCostEstimation:
    def test_estimate_cost_claude_opus(self):
        cost = estimate_cost("claude-opus-4-8", 1000, 500)
        assert cost is not None
        assert cost > 0
        expected = (1000 * 15.0 + 500 * 75.0) / 1_000_000
        assert abs(cost - expected) < 1e-10

    def test_estimate_cost_gpt4o(self):
        cost = estimate_cost("gpt-4o", 1000, 500)
        assert cost is not None
        expected = (1000 * 2.5 + 500 * 10.0) / 1_000_000
        assert abs(cost - expected) < 1e-10

    def test_estimate_cost_unknown_model(self):
        cost = estimate_cost("unknown-model-xyz", 1000, 500)
        assert cost is None

    def test_estimate_cost_zero_tokens(self):
        cost = estimate_cost("claude-opus-4-8", 0, 0)
        assert cost == 0.0

    def test_pricing_table_has_common_models(self):
        assert "claude-opus-4" in MODEL_PRICING
        assert "gpt-4o" in MODEL_PRICING
        assert "qwen-plus" in MODEL_PRICING
        assert "deepseek-chat" in MODEL_PRICING


class TestBackendDetection:
    def test_detect_with_anthropic_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        assert detect_available_backend() == "anthropic"

    def test_detect_with_dashscope_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
        assert detect_available_backend() == "qwen"

    def test_detect_no_keys(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        result = detect_available_backend()
        assert result is None or result == "claude-cli"

    def test_validate_backend_anthropic(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        assert validate_backend("anthropic") is True

    def test_validate_backend_missing_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert validate_backend("anthropic") is False

    def test_resolve_backend_auto(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        assert resolve_backend("auto") == "anthropic"

    def test_resolve_backend_strict_missing(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(ValueError, match="no valid credentials"):
            resolve_backend("anthropic", strict=True)
