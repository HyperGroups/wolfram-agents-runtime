"""A tiny, dependency-free web server that exposes the runtime's live state.

Supports multiple notebooks with independent graphs and histories.

    GET  /                        -> the monitor web app
    GET  /api/notebooks           -> list all notebooks
    GET  /api/notebooks/<id>      -> get notebook details (graph, inputs, etc.)
    POST /api/notebooks           -> create a new notebook
    POST /api/notebooks/<id>/activate -> set active notebook
    POST /api/notebooks/<id>/run  -> run the active notebook
    GET  /api/notebooks/<id>/runs -> list runs for a notebook
    GET  /api/notebooks/<id>/runs/<run_id> -> get a specific run trace
    POST /api/notebooks/<id>/runs/compare -> get multiple run traces for comparison
    GET  /api/graph               -> active notebook's graph structure
    GET  /api/langgraph           -> active notebook's compiled LangGraph
    GET  /api/state               -> active notebook's current run snapshot
    GET  /api/events              -> SSE stream for active notebook
    GET  /api/node/<name>/output  -> get full output for a node
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty

from .notebook import NotebookManager

_WEBAPP = Path(__file__).parent / "webapp" / "index.html"


class MonitorServer:
    """Holds notebooks and runs evaluations one at a time per notebook."""

    def __init__(self, notebook_manager: NotebookManager, *, prop="All"):
        self.nb_manager = notebook_manager
        self.prop = prop
        self._run_locks: dict[str, threading.Lock] = {}
        self._running: dict[str, bool] = {}

    def _get_lock(self, notebook_id: str) -> threading.Lock:
        if notebook_id not in self._run_locks:
            self._run_locks[notebook_id] = threading.Lock()
        return self._run_locks[notebook_id]

    def run_async(self, notebook_id: str, input_dict: dict) -> bool:
        nb = self.nb_manager.get_notebook(notebook_id)
        if nb is None:
            return False

        lock = self._get_lock(notebook_id)
        with lock:
            if self._running.get(notebook_id):
                return False
            self._running[notebook_id] = True

        def worker():
            try:
                nb.graph(input_dict, self.prop)
                if nb.monitor.last_run_id:
                    self.nb_manager.save_run(notebook_id, nb.monitor.last_run_id)
            except Exception as exc:
                import traceback
                traceback.print_exc()
                if nb.monitor and nb.monitor.last_run_id:
                    nb.monitor.end_run(nb.monitor.last_run_id, status="error")
                    for name in (nb.graph.nodes if hasattr(nb.graph, 'nodes') else {}):
                        rec = nb.monitor._rec(nb.monitor.last_run_id, name)
                        if rec and rec.status == "running":
                            nb.monitor.node_error(nb.monitor.last_run_id, name, str(exc))
                try:
                    self.nb_manager.save_run(notebook_id, nb.monitor.last_run_id)
                except Exception:
                    pass
            finally:
                with lock:
                    self._running[notebook_id] = False

        threading.Thread(target=worker, daemon=True).start()
        return True


def _make_handler(app: MonitorServer):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, ctype, body: bytes):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, "application/json; charset=utf-8",
                       json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"))

        def do_GET(self):
            path = self.path.split("?")[0]
            parts = path.strip("/").split("/")

            # Static files
            if path in ("/", "/index.html"):
                try:
                    html = _WEBAPP.read_text(encoding="utf-8")
                except OSError:
                    return self._send(500, "text/plain", b"webapp/index.html missing")
                return self._send(200, "text/html; charset=utf-8", html.encode("utf-8"))

            # Notebook list
            if path == "/api/notebooks":
                return self._json(app.nb_manager.list_notebooks())

            # Specific notebook
            if len(parts) == 2 and parts[0] == "api" and parts[1].startswith("notebooks_"):
                nb_id = parts[1].replace("notebooks_", "")
                nb = app.nb_manager.get_notebook(nb_id)
                if nb is None:
                    return self._json({"error": "notebook not found"}, code=404)
                return self._json({
                    "id": nb.id,
                    "name": nb.name,
                    "source_file": nb.source_file,
                    "default_input": nb.default_input,
                    "created_at": nb.created_at,
                    "last_run_at": nb.last_run_at,
                })

            # Notebook runs list
            if len(parts) == 3 and parts[0] == "api" and parts[1].startswith("notebooks_") and parts[2] == "runs":
                nb_id = parts[1].replace("notebooks_", "")
                runs = app.nb_manager.list_runs(nb_id)
                return self._json(runs)

            # Specific run trace
            if len(parts) == 4 and parts[0] == "api" and parts[1].startswith("notebooks_") and parts[2] == "runs":
                nb_id = parts[1].replace("notebooks_", "")
                run_id = parts[3]
                trace = app.nb_manager.load_run(nb_id, run_id)
                if trace is None:
                    return self._json({"error": "run not found"}, code=404)
                return self._json(trace)

            # Active notebook APIs
            nb = app.nb_manager.get_notebook()
            if nb is None:
                return self._json({"error": "no active notebook"}, code=404)

            if path == "/api/graph":
                return self._json(nb.graph.information())

            if path == "/api/langgraph":
                try:
                    return self._json(nb.graph.langgraph_structure())
                except Exception as exc:
                    return self._json({"error": str(exc)}, code=500)

            if path == "/api/state":
                return self._json(nb.monitor.snapshot() or {})

            if path.startswith("/api/node/") and path.endswith("/output"):
                node_parts = path.split("/")
                if len(node_parts) == 5:
                    node_name = node_parts[3]
                    result = nb.monitor.get_node_output(None, node_name)
                    if result is None:
                        return self._json({"error": "node not found"}, code=404)
                    return self._json(result)

            if path == "/api/events":
                return self._sse(nb)

            return self._send(404, "text/plain", b"not found")

        def do_POST(self):
            path = self.path.split("?")[0]
            parts = path.strip("/").split("/")

            # Create notebook
            if path == "/api/notebooks":
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b"{}"
                try:
                    body = json.loads(raw)
                except Exception:
                    return self._json({"error": "invalid JSON"}, code=400)

                name = body.get("name", "Untitled")
                source_file = body.get("source_file")
                if not source_file:
                    return self._json({"error": "source_file required"}, code=400)

                try:
                    nb = app.nb_manager.create_notebook(
                        name=name,
                        source_file=source_file,
                        default_input=body.get("default_input", {}),
                        backend=body.get("backend"),
                        model=body.get("model"),
                    )
                    return self._json({"id": nb.id, "name": nb.name})
                except Exception as e:
                    return self._json({"error": str(e)}, code=400)

            # Activate notebook
            if len(parts) == 3 and parts[0] == "api" and parts[1].startswith("notebooks_") and parts[2] == "activate":
                nb_id = parts[1].replace("notebooks_", "")
                try:
                    app.nb_manager.set_active(nb_id)
                    return self._json({"active": nb_id})
                except ValueError as e:
                    return self._json({"error": str(e)}, code=404)

            # Run notebook
            if len(parts) == 3 and parts[0] == "api" and parts[1].startswith("notebooks_") and parts[2] == "run":
                nb_id = parts[1].replace("notebooks_", "")
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b"{}"
                try:
                    body = json.loads(raw)
                except Exception:
                    body = {}
                nb = app.nb_manager.get_notebook(nb_id)
                if nb is None:
                    return self._json({"error": "notebook not found"}, code=404)
                input_dict = body.get("input", nb.default_input)
                started = app.run_async(nb_id, input_dict)
                return self._json({"started": started})

            # Compare multiple runs
            if len(parts) == 4 and parts[0] == "api" and parts[1].startswith("notebooks_") and parts[2] == "runs" and parts[3] == "compare":
                nb_id = parts[1].replace("notebooks_", "")
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b"{}"
                try:
                    body = json.loads(raw)
                except Exception:
                    return self._json({"error": "invalid JSON"}, code=400)
                
                run_ids = body.get("run_ids", [])
                if not run_ids or not isinstance(run_ids, list):
                    return self._json({"error": "run_ids must be a non-empty list"}, code=400)
                
                traces = []
                for run_id in run_ids:
                    trace = app.nb_manager.load_run(nb_id, run_id)
                    if trace is None:
                        return self._json({"error": f"run {run_id} not found"}, code=404)
                    traces.append(trace)
                
                return self._json({"traces": traces})

            # Run active notebook
            if path == "/api/run":
                nb = app.nb_manager.get_notebook()
                if nb is None:
                    return self._json({"error": "no active notebook"}, code=404)
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b"{}"
                try:
                    body = json.loads(raw)
                except Exception:
                    body = {}
                input_dict = body.get("input", nb.default_input)
                started = app.run_async(nb.id, input_dict)
                return self._json({"started": started})

            return self._send(404, "text/plain", b"not found")

        def _sse(self, nb):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            q = nb.monitor.subscribe()
            try:
                snap = nb.monitor.snapshot()
                if snap:
                    self._event({"type": "snapshot", "run": snap})
                while True:
                    try:
                        self._event(q.get(timeout=15))
                    except Empty:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                nb.monitor.unsubscribe(q)

        def _event(self, obj):
            payload = json.dumps(obj, ensure_ascii=False, default=str)
            self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
            self.wfile.flush()

    return Handler


def serve(graph, monitor, host="127.0.0.1", port=8765, default_input=None, prop="All"):
    """Legacy serve function for backward compatibility."""
    nb_manager = NotebookManager()
    # Create a default notebook from the provided graph
    nb_manager.notebooks["default"] = None  # placeholder
    # Actually, we need to create a proper notebook
    from .notebook import Notebook
    from datetime import datetime
    nb = Notebook(
        id="default",
        name="Default",
        source_file="memory",
        graph=graph,
        monitor=monitor,
        default_input=default_input or {},
        created_at=datetime.now().isoformat(),
    )
    nb_manager.notebooks["default"] = nb
    nb_manager.active_id = "default"

    app = MonitorServer(nb_manager, prop=prop)
    httpd = ThreadingHTTPServer((host, port), _make_handler(app))
    return httpd, app


def serve_notebooks(notebook_manager: NotebookManager, host="127.0.0.1", port=8765, prop="All"):
    """Serve multiple notebooks."""
    app = MonitorServer(notebook_manager, prop=prop)
    httpd = ThreadingHTTPServer((host, port), _make_handler(app))
    return httpd, app
