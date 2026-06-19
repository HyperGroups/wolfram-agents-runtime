"""Notebook management for the LLMGraph runtime.

A notebook is a self-contained working unit:
  - A graph definition (JSON or WLS)
  - Default input configuration
  - Run history (traces)
  - Frontend state (last selected view, etc.)

Notebooks are stored in .llmgraph_runs/notebooks/<id>/
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .core import LLMGraph
from .monitor import RunMonitor


@dataclass
class Notebook:
    """A self-contained graph working unit."""
    
    id: str
    name: str
    source_file: str  # .json or .wls path
    graph: LLMGraph
    monitor: RunMonitor
    default_input: dict = field(default_factory=dict)
    created_at: str = ""
    last_run_at: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


class NotebookManager:
    """Manages multiple notebooks with independent graphs and histories."""
    
    def __init__(self, runs_dir: str = ".llmgraph_runs"):
        self.runs_dir = Path(runs_dir)
        self.notebooks_dir = self.runs_dir / "notebooks"
        self.notebooks_dir.mkdir(parents=True, exist_ok=True)
        self.notebooks: dict[str, Notebook] = {}
        self.active_id: str | None = None
        self._load_registry()
    
    def _registry_path(self) -> Path:
        return self.runs_dir / "notebooks.json"
    
    def _load_registry(self):
        """Load notebook registry from disk."""
        path = self._registry_path()
        if not path.exists():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for entry in data.get("notebooks", []):
                # Notebooks are lazily loaded when accessed
                pass
        except Exception:
            pass
    
    def _save_registry(self):
        """Save notebook registry to disk."""
        data = {
            "notebooks": [
                {
                    "id": nb.id,
                    "name": nb.name,
                    "source_file": nb.source_file,
                    "default_input": nb.default_input,
                    "created_at": nb.created_at,
                    "last_run_at": nb.last_run_at,
                }
                for nb in self.notebooks.values()
            ],
            "active_id": self.active_id,
        }
        with open(self._registry_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def _notebook_dir(self, notebook_id: str) -> Path:
        return self.notebooks_dir / notebook_id
    
    def _runs_dir_for(self, notebook_id: str) -> Path:
        d = self._notebook_dir(notebook_id) / "runs"
        d.mkdir(parents=True, exist_ok=True)
        return d
    
    def load_graph_from_file(self, file_path: str, *, backend_strict: bool = False) -> LLMGraph:
        """Load a graph from a JSON or WLS file."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Graph file not found: {file_path}")
        
        if path.suffix == ".json":
            return self._load_json_graph(path, backend_strict=backend_strict)
        elif path.suffix in (".wls", ".wl"):
            return self._load_wls_graph(path, backend_strict=backend_strict)
        else:
            raise ValueError(f"Unsupported file type: {path.suffix}")
    
    def _load_json_graph(self, path: Path, *, backend_strict: bool = False) -> LLMGraph:
        """Load graph from JSON file."""
        from .loaders import load_json
        return load_json(str(path), backend_strict=backend_strict)
    
    def _load_wls_graph(self, path: Path, *, backend_strict: bool = False) -> LLMGraph:
        """Load graph from WLS file by transpiling to JSON first."""
        # Try to find transpiler
        transpiler = path.parent / "wlg2json.wls"
        if not transpiler.exists():
            # Try common locations
            for candidate in [
                Path("tools/wlg2json.wls"),
                Path("wolfram-agents-runtime/tools/wlg2json.wls"),
            ]:
                if candidate.exists():
                    transpiler = candidate
                    break
        
        if not transpiler.exists():
            raise RuntimeError(
                f"Cannot transpile WLS file: transpiler not found. "
                f"Place wlg2json.wls in the same directory or tools/"
            )
        
        # Run transpiler
        try:
            result = subprocess.run(
                ["wolframscript", "-file", str(transpiler), str(path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Transpiler failed: {result.stderr}")
            
            # Parse JSON output
            graph_spec = json.loads(result.stdout)
            from .loaders import _build_graph_from_spec
            return _build_graph_from_spec(graph_spec, backend_strict=backend_strict)
        except subprocess.TimeoutExpired:
            raise RuntimeError("Transpiler timed out")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid transpiler output: {e}")
    
    def create_notebook(
        self,
        name: str,
        source_file: str,
        default_input: dict | None = None,
        backend: str | None = None,
        model: str | None = None,
        backend_strict: bool = False,
    ) -> Notebook:
        """Create a new notebook from a graph file."""
        graph = self.load_graph_from_file(source_file, backend_strict=backend_strict)
        
        if backend:
            from .backends import resolve_backend
            graph.backend = resolve_backend(backend, strict=backend_strict)
        if model:
            graph.model = model
        
        notebook_id = f"nb_{int(time.time())}_{name.lower().replace(' ', '_')[:20]}"
        monitor = RunMonitor()
        graph.monitor = monitor
        
        nb = Notebook(
            id=notebook_id,
            name=name,
            source_file=str(Path(source_file).resolve()),
            graph=graph,
            monitor=monitor,
            default_input=default_input or {},
        )
        
        self.notebooks[notebook_id] = nb
        if self.active_id is None:
            self.active_id = notebook_id
        
        self._save_registry()
        return nb
    
    def get_notebook(self, notebook_id: str | None = None) -> Notebook | None:
        """Get a notebook by ID, or the active one."""
        nid = notebook_id or self.active_id
        if nid is None:
            return None
        return self.notebooks.get(nid)
    
    def set_active(self, notebook_id: str):
        """Set the active notebook."""
        if notebook_id not in self.notebooks:
            raise ValueError(f"Notebook not found: {notebook_id}")
        self.active_id = notebook_id
        self._save_registry()
    
    def list_notebooks(self) -> list[dict]:
        """List all notebooks with summary info."""
        result = []
        for nb in self.notebooks.values():
            runs_dir = self._runs_dir_for(nb.id)
            run_count = len(list(runs_dir.glob("*.json")))
            result.append({
                "id": nb.id,
                "name": nb.name,
                "source_file": nb.source_file,
                "default_input": nb.default_input,
                "created_at": nb.created_at,
                "last_run_at": nb.last_run_at,
                "run_count": run_count,
                "is_active": nb.id == self.active_id,
            })
        return result
    
    def save_run(self, notebook_id: str, run_id: str):
        """Save a run trace to the notebook's runs directory."""
        nb = self.notebooks.get(notebook_id)
        if nb is None:
            raise ValueError(f"Notebook not found: {notebook_id}")
        
        runs_dir = self._runs_dir_for(notebook_id)
        trace = nb.monitor._build_trace(run_id)
        
        file_path = runs_dir / f"{run_id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(trace, f, indent=2, ensure_ascii=False, default=str)
        
        nb.last_run_at = datetime.now().isoformat()
        self._save_registry()
    
    def list_runs(self, notebook_id: str) -> list[dict]:
        """List runs for a specific notebook."""
        runs_dir = self._runs_dir_for(notebook_id)
        if not runs_dir.exists():
            return []
        
        runs = []
        for file_path in sorted(runs_dir.glob("*.json"), reverse=True):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    trace = json.load(f)
                runs.append({
                    "run_id": trace["run_id"],
                    "timestamp": trace["timestamp"],
                    "duration": trace["duration"],
                    "status": trace["status"],
                    "input": trace.get("input", {}),
                    "output_summary": {
                        k: (v[:80] + "..." if isinstance(v, str) and len(v) > 80 else v)
                        for k, v in trace.get("output", {}).items()
                    },
                })
            except Exception:
                continue
        return runs
    
    def load_run(self, notebook_id: str, run_id: str) -> dict | None:
        """Load a specific run trace."""
        file_path = self._runs_dir_for(notebook_id) / f"{run_id}.json"
        if not file_path.exists():
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
