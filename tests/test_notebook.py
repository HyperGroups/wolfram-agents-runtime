"""Tests for NotebookManager - the backbone of multi-notebook server."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from wolfram_llmgraph.notebook import NotebookManager, Notebook
from wolfram_llmgraph import LLMGraph, RunMonitor


def _fake_factory():
    class _Resp:
        def __init__(self, c):
            self.content = c

    class _LLM:
        def __init__(self, model):
            self.model = model

        async def ainvoke(self, prompt):
            return _Resp(f"[{self.model}] {prompt}")

    return lambda model: _LLM(model)


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield td


@pytest.fixture
def sample_graph_file(temp_dir):
    """Create a sample graph JSON file with LLM nodes (no callables needed)."""
    graph_data = {
        "nodes": {
            "A": "prompt A",
            "B": "prompt B with `A`"
        },
        "output": ["B"]
    }
    path = Path(temp_dir) / "test_graph.json"
    with open(path, "w") as f:
        json.dump(graph_data, f)
    return str(path)


@pytest.fixture
def notebook_manager(temp_dir):
    """Create a NotebookManager with a temp directory."""
    runs_dir = os.path.join(temp_dir, ".llmgraph_runs")
    return NotebookManager(runs_dir=runs_dir)


class TestNotebookManager:
    def test_create_notebook(self, notebook_manager, sample_graph_file):
        """Test creating a new notebook."""
        nb = notebook_manager.create_notebook(
            name="Test Notebook",
            source_file=sample_graph_file,
            default_input={"x": 1}
        )
        assert nb.id is not None
        assert nb.name == "Test Notebook"
        assert Path(nb.source_file).resolve() == Path(sample_graph_file).resolve()
        assert nb.default_input == {"x": 1}
        assert nb.graph is not None
        assert nb.monitor is not None

    def test_list_notebooks(self, notebook_manager, sample_graph_file):
        """Test listing notebooks."""
        nb1 = notebook_manager.create_notebook("NB1", sample_graph_file)
        nb2 = notebook_manager.create_notebook("NB2", sample_graph_file)
        
        notebooks = notebook_manager.list_notebooks()
        assert len(notebooks) == 2
        ids = [nb["id"] for nb in notebooks]
        assert nb1.id in ids
        assert nb2.id in ids

    def test_get_notebook(self, notebook_manager, sample_graph_file):
        """Test getting a notebook by ID."""
        nb = notebook_manager.create_notebook("Test", sample_graph_file)
        retrieved = notebook_manager.get_notebook(nb.id)
        assert retrieved is not None
        assert retrieved.id == nb.id
        assert retrieved.name == nb.name

    def test_get_notebook_none_for_invalid_id(self, notebook_manager):
        """Test getting a notebook with invalid ID returns None."""
        result = notebook_manager.get_notebook("nonexistent")
        assert result is None

    def test_set_active_notebook(self, notebook_manager, sample_graph_file):
        """Test setting the active notebook."""
        nb1 = notebook_manager.create_notebook("NB1", sample_graph_file)
        nb2 = notebook_manager.create_notebook("NB2", sample_graph_file)
        
        notebook_manager.set_active(nb2.id)
        assert notebook_manager.active_id == nb2.id
        
        active = notebook_manager.get_notebook()
        assert active is not None
        assert active.id == nb2.id

    def test_first_notebook_becomes_active(self, notebook_manager, sample_graph_file):
        """Test that the first notebook created becomes active."""
        nb = notebook_manager.create_notebook("First", sample_graph_file)
        assert notebook_manager.active_id == nb.id

    def test_save_and_load_run(self, notebook_manager, sample_graph_file):
        """Test saving and loading a run."""
        nb = notebook_manager.create_notebook("Test", sample_graph_file)
        
        # Simulate a run
        nb.monitor.start_run("run-123", nb.graph.information(), {})
        nb.monitor.node_running("run-123", "A")
        nb.monitor.node_finished("run-123", "A", 42)
        nb.monitor.node_running("run-123", "B")
        nb.monitor.node_finished("run-123", "B", 84)
        nb.monitor.end_run("run-123", "done")
        
        # Save the run
        notebook_manager.save_run(nb.id, "run-123")
        
        # List runs
        runs = notebook_manager.list_runs(nb.id)
        assert len(runs) == 1
        assert runs[0]["run_id"] == "run-123"
        assert runs[0]["status"] == "done"
        
        # Load the run
        trace = notebook_manager.load_run(nb.id, "run-123")
        assert trace is not None
        assert trace["run_id"] == "run-123"
        assert trace["status"] == "done"
        assert len(trace["spans"]) == 2

    def test_list_runs_empty(self, notebook_manager, sample_graph_file):
        """Test listing runs when none exist."""
        nb = notebook_manager.create_notebook("Test", sample_graph_file)
        runs = notebook_manager.list_runs(nb.id)
        assert runs == []

    def test_load_nonexistent_run(self, notebook_manager, sample_graph_file):
        """Test loading a run that doesn't exist."""
        nb = notebook_manager.create_notebook("Test", sample_graph_file)
        trace = notebook_manager.load_run(nb.id, "nonexistent")
        assert trace is None

    def test_registry_persistence(self, temp_dir, sample_graph_file):
        """Test that notebook registry file is created."""
        runs_dir = os.path.join(temp_dir, ".llmgraph_runs")
        
        # Create first manager and notebook
        mgr1 = NotebookManager(runs_dir=runs_dir)
        nb1 = mgr1.create_notebook("NB1", sample_graph_file)
        
        # Registry file should exist
        registry_path = Path(runs_dir) / "notebooks.json"
        assert registry_path.exists()
        
        # Registry should contain the notebook metadata
        with open(registry_path, "r") as f:
            data = json.load(f)
        assert len(data["notebooks"]) == 1
        assert data["notebooks"][0]["id"] == nb1.id
        assert data["active_id"] == nb1.id


class TestNotebook:
    def test_notebook_dataclass(self, sample_graph_file):
        """Test Notebook dataclass creation."""
        graph = LLMGraph({"A": "prompt A"}, llm_factory=_fake_factory())
        monitor = RunMonitor()
        
        nb = Notebook(
            id="test-id",
            name="Test",
            source_file=sample_graph_file,
            graph=graph,
            monitor=monitor,
            default_input={"x": 1}
        )
        
        assert nb.id == "test-id"
        assert nb.name == "Test"
        assert nb.source_file == sample_graph_file
        assert nb.graph is graph
        assert nb.monitor is monitor
        assert nb.default_input == {"x": 1}
        assert nb.created_at is not None
        assert nb.last_run_at == ""
