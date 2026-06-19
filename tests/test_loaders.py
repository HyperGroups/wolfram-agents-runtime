"""Tests for loaders module - JSON graph loading and parsing."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from wolfram_llmgraph.loaders import from_dict, load_json, _build_graph_from_spec


class TestFromDict:
    """Tests for from_dict() function."""
    
    def test_basic_graph(self):
        """Test loading a basic graph with string prompts."""
        data = {
            "nodes": {
                "A": "prompt A",
                "B": "prompt B with `A`"
            }
        }
        graph = from_dict(data)
        assert set(graph.nodes.keys()) == {"A", "B"}
        assert graph.nodes["A"].kind == "llm"
        assert graph.nodes["B"].kind == "llm"
    
    def test_missing_nodes_key(self):
        """Test that missing 'nodes' key raises ValueError."""
        data = {"output": ["A"]}
        with pytest.raises(ValueError, match="must contain a 'nodes' object"):
            from_dict(data)
    
    def test_empty_nodes(self):
        """Test that empty nodes dict works."""
        data = {"nodes": {}}
        # LLMGraph itself will raise ValueError for empty nodes
        with pytest.raises(ValueError):
            from_dict(data)
    
    def test_with_output_field(self):
        """Test loading graph with explicit output field."""
        data = {
            "nodes": {
                "A": "prompt A",
                "B": "prompt B",
                "C": "prompt C"
            },
            "output": ["B", "C"]
        }
        graph = from_dict(data)
        assert graph.outputs == ["B", "C"]
    
    def test_with_model_field(self):
        """Test loading graph with model field."""
        data = {
            "nodes": {"A": "prompt A"},
            "model": "gpt-4"
        }
        graph = from_dict(data)
        assert graph.model == "gpt-4"
    
    def test_with_backend_field(self):
        """Test loading graph with backend field."""
        data = {
            "nodes": {"A": "prompt A"},
            "backend": "openai"
        }
        # This will fail if OPENAI_API_KEY is not set and backend_strict=True
        # but should work with auto-detection
        graph = from_dict(data, backend_strict=False)
        assert graph.backend in ["openai", "anthropic", "claude-cli", "qwen", "qwen-tokenplan", "deepseek"]
    
    def test_node_with_dict_spec(self):
        """Test loading graph with dict node specs."""
        data = {
            "nodes": {
                "A": {"prompt": "prompt A", "model": "gpt-4"},
                "B": {"prompt": "prompt B with `A`"}
            }
        }
        graph = from_dict(data)
        assert graph.nodes["A"].model == "gpt-4"
        assert graph.nodes["B"].model is None
    
    def test_listable_llm_node(self):
        """Test loading graph with listable_llm node."""
        data = {
            "nodes": {
                "Translate": {
                    "listable_llm": "Translate `words` to French",
                    "input": ["words"]
                }
            }
        }
        graph = from_dict(data)
        assert graph.nodes["Translate"].kind == "listable_llm"
        assert graph.nodes["Translate"].list_inputs == ["words"]
    
    def test_backend_strict_parameter(self):
        """Test that backend_strict parameter is passed through."""
        data = {
            "nodes": {"A": "prompt A"},
            "backend": "nonexistent"
        }
        # With backend_strict=False, it should auto-detect
        graph = from_dict(data, backend_strict=False)
        assert graph.backend != "nonexistent"


class TestLoadJson:
    """Tests for load_json() function."""
    
    def test_load_from_file(self, tmp_path):
        """Test loading graph from JSON file."""
        data = {
            "nodes": {
                "A": "prompt A",
                "B": "prompt B with `A`"
            }
        }
        file_path = tmp_path / "graph.json"
        with open(file_path, "w") as f:
            json.dump(data, f)
        
        graph = load_json(str(file_path))
        assert set(graph.nodes.keys()) == {"A", "B"}
    
    def test_load_from_string(self):
        """Test loading graph from JSON string."""
        json_str = json.dumps({
            "nodes": {
                "A": "prompt A",
                "B": "prompt B"
            }
        })
        graph = load_json(json_str)
        assert set(graph.nodes.keys()) == {"A", "B"}
    
    def test_file_not_found(self):
        """Test that non-existent file path is treated as JSON string."""
        # If the path doesn't exist, load_json tries to parse it as JSON
        with pytest.raises(json.JSONDecodeError):
            load_json("/nonexistent/path/graph.json")
    
    def test_invalid_json_string(self):
        """Test that invalid JSON string raises error."""
        with pytest.raises(json.JSONDecodeError):
            load_json("not valid json")
    
    def test_load_with_all_fields(self, tmp_path, monkeypatch):
        """Test loading graph with all optional fields from file."""
        # Set ANTHROPIC_API_KEY to prevent auto-switching
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        
        data = {
            "nodes": {
                "A": "prompt A",
                "B": "prompt B with `A`"
            },
            "output": ["B"],
            "model": "claude-3-opus-20240229",
            "backend": "anthropic"
        }
        file_path = tmp_path / "graph.json"
        with open(file_path, "w") as f:
            json.dump(data, f)
        
        graph = load_json(str(file_path))
        assert graph.outputs == ["B"]
        assert graph.model == "claude-3-opus-20240229"
        assert graph.backend == "anthropic"
    
    def test_backend_strict_parameter(self, tmp_path):
        """Test that backend_strict parameter is passed through."""
        data = {
            "nodes": {"A": "prompt A"},
            "backend": "nonexistent"
        }
        file_path = tmp_path / "graph.json"
        with open(file_path, "w") as f:
            json.dump(data, f)
        
        # With backend_strict=False, it should auto-detect
        graph = load_json(str(file_path), backend_strict=False)
        assert graph.backend != "nonexistent"


class TestBuildGraphFromSpec:
    """Tests for _build_graph_from_spec() function."""
    
    def test_basic_spec(self):
        """Test building graph from basic spec."""
        spec = {
            "nodes": {
                "A": "prompt A",
                "B": "prompt B with `A`"
            }
        }
        graph = _build_graph_from_spec(spec)
        assert set(graph.nodes.keys()) == {"A", "B"}
    
    def test_with_backend_strict(self):
        """Test that backend_strict parameter is passed through."""
        spec = {
            "nodes": {"A": "prompt A"},
            "backend": "nonexistent"
        }
        graph = _build_graph_from_spec(spec, backend_strict=False)
        assert graph.backend != "nonexistent"
    
    def test_wrapper_equivalence(self):
        """Test that _build_graph_from_spec is equivalent to from_dict."""
        spec = {
            "nodes": {
                "A": "prompt A",
                "B": "prompt B"
            },
            "output": ["B"],
            "model": "gpt-4"
        }
        graph1 = from_dict(spec)
        graph2 = _build_graph_from_spec(spec)
        
        assert set(graph1.nodes.keys()) == set(graph2.nodes.keys())
        assert graph1.outputs == graph2.outputs
        assert graph1.model == graph2.model
