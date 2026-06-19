"""Load an :class:`LLMGraph` from JSON.

JSON graph schema::

    {
      "nodes": {
        "Poet1": "write a short poem about summer",
        "Judge": {"prompt": "pick the best: `Poet1`", "model": "claude-opus-4-8"}
      },
      "output": ["Judge"],     // optional; defaults to sink nodes
      "model": "claude-opus-4-8" // optional graph-wide default model
    }

Code (callable) nodes cannot be expressed in JSON; build those with the
Python API (:class:`wolfram_llmgraph.LLMGraph`).
"""

from __future__ import annotations

import json
import os
from typing import Any, Mapping

from .core import LLMGraph


def from_dict(data: Mapping[str, Any], *, backend_strict: bool = False) -> LLMGraph:
    if "nodes" not in data:
        raise ValueError("Graph definition must contain a 'nodes' object")
    
    return LLMGraph(
        data["nodes"],
        output=data.get("output"),
        model=data.get("model"),
        backend=data.get("backend"),
        backend_strict=backend_strict,
    )


def _build_graph_from_spec(data: Mapping[str, Any], *, backend_strict: bool = False) -> LLMGraph:
    """Build an LLMGraph from a parsed spec dict (used by WLS transpiler)."""
    return from_dict(data, backend_strict=backend_strict)


def load_json(source: str, *, backend_strict: bool = False) -> LLMGraph:
    """Load from a file path, or from a raw JSON string if it isn't a path."""
    if os.path.exists(source):
        with open(source, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    else:
        data = json.loads(source)
    return from_dict(data, backend_strict=backend_strict)
