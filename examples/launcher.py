"""Launch the runtime monitor with multiple notebook support.

Scans examples/ for graph files (.json and .wls) and creates notebooks for each.

需要 DASHSCOPE_API_KEY 环境变量，或在 .env 文件中设置。

    python examples/launcher.py                      # -> http://127.0.0.1:8765/
    python examples/launcher.py --port 9000 --open
    python examples/launcher.py --examples-dir examples/
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)


_load_dotenv()

# 绕过系统代理，直连 DashScope API
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

from wolfram_llmgraph.notebook import NotebookManager
from wolfram_llmgraph.server import serve_notebooks


def find_graph_files(examples_dir: str) -> list[Path]:
    """Find all graph files in the examples directory."""
    examples = Path(examples_dir)
    if not examples.exists():
        return []
    
    files = []
    for ext in ("*.json", "*.wls", "*.wl"):
        files.extend(examples.glob(ext))
    
    # Filter out non-graph files
    graph_files = []
    for f in files:
        # Skip known non-graph files
        if f.name in ("sources.json", "package.json"):
            continue
        if "wolfram-docs" in str(f):
            continue
        if f.name.startswith("_"):
            continue
        graph_files.append(f)
    
    return sorted(graph_files)


def main():
    p = argparse.ArgumentParser(description="Launch LLMGraph monitor with notebook support")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--open", action="store_true", help="Open browser on start")
    p.add_argument("--examples-dir", default="examples", help="Directory containing graph files")
    p.add_argument("--backend", default="qwen", help="Default LLM backend")
    p.add_argument("--model", default="qwen-plus", help="Default LLM model")
    args = p.parse_args()
    
    # Create notebook manager
    nb_manager = NotebookManager()
    
    # Find and load graph files
    graph_files = find_graph_files(args.examples_dir)
    if not graph_files:
        print(f"No graph files found in {args.examples_dir}", file=sys.stderr)
        print("Creating a default demo notebook...", file=sys.stderr)
        
        # Create a simple demo notebook
        from wolfram_llmgraph import LLMGraph, RunMonitor
        from wolfram_llmgraph.notebook import Notebook
        from datetime import datetime
        
        monitor = RunMonitor()
        graph = LLMGraph(
            {
                "Greeting": "Say hello to `Name` in a creative way",
            },
            monitor=monitor,
            backend=args.backend,
            model=args.model,
        )
        nb = Notebook(
            id="nb_demo",
            name="Demo",
            source_file="memory",
            graph=graph,
            monitor=monitor,
            default_input={"Name": "World"},
            created_at=datetime.now().isoformat(),
        )
        nb_manager.notebooks[nb.id] = nb
        nb_manager.active_id = nb.id
    else:
        print(f"Found {len(graph_files)} graph files:", file=sys.stderr)
        for gf in graph_files:
            print(f"  - {gf.name}", file=sys.stderr)
            
            # Create notebook for each graph file
            try:
                nb = nb_manager.create_notebook(
                    name=gf.stem.replace("_", " ").title(),
                    source_file=str(gf),
                    backend=args.backend,
                    model=args.model,
                )
                print(f"    -> notebook: {nb.id}", file=sys.stderr)
            except Exception as e:
                print(f"    -> error: {e}", file=sys.stderr)
    
    if not nb_manager.notebooks:
        print("No notebooks could be created", file=sys.stderr)
        return 1
    
    # Start server
    httpd, _ = serve_notebooks(nb_manager, host=args.host, port=args.port)
    url = f"http://{args.host}:{args.port}/"
    print(f"\nLLMGraph monitor on {url}  (Ctrl-C to stop)", flush=True)
    print(f"Active notebook: {nb_manager.get_notebook().name}", flush=True)
    
    if args.open:
        import webbrowser
        webbrowser.open(url)
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping…", file=sys.stderr)
    finally:
        httpd.shutdown()
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
