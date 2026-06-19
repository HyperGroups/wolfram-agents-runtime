"""Sequential mode: test first, then execute.

This is the default mode. Conditional nodes wait for test dependencies,
evaluate the test, and only execute if the test passes.

Advantages:
- Saves LLM calls when test fails
- More efficient when test is cheap

Disadvantages:
- Serial execution: can't parallelize LLM calls with test evaluation
"""

from __future__ import annotations

import argparse
import os


def _load_dotenv(path: str = ".env") -> None:
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
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

from wolfram_llmgraph import LLMGraph, RunMonitor
from wolfram_llmgraph.server import serve


def build_graph(monitor: RunMonitor) -> LLMGraph:
    """Build CorrectWorkflow in sequential mode."""
    
    return LLMGraph(
        {
            "Decide": "Decide if the following contains errors. Respond with either 'Correct' or 'Errors':\n\n`Input`",
            
            "Review": {
                "prompt": "List any errors in the following:\n\n`Input`",
                "test": lambda Decide: "Errors" in str(Decide),
            },
            
            "Rewrite": {
                "prompt": "Rewrite the following text to fix any issues specified in the critique:\n\n=== Text ===\n`Input`\n\n=== Critique ===\n`Review`\n",
                "test": lambda Review: isinstance(Review, str) and len(Review) > 0,
            },
            
            "Final": {
                "fn": lambda Rewrite, Input: (
                    f"Incorrect input:\n{Input}\nhas been rewritten as:\n{Rewrite}"
                    if isinstance(Rewrite, str) and len(Rewrite) > 0
                    else str(Input)
                ),
                "input": ["Rewrite", "Input"],
            },
        },
        monitor=monitor,
        backend="qwen",
        model="qwen-plus",
        speculative=False,  # Sequential mode
    )


def main():
    p = argparse.ArgumentParser(description="Run CorrectWorkflow (sequential mode)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--open", action="store_true")
    p.add_argument("--input", default="The quik brown fox jump over the lazy dog.")
    args = p.parse_args()
    
    monitor = RunMonitor()
    graph = build_graph(monitor)
    
    httpd, _ = serve(
        graph, monitor,
        host=args.host, port=args.port,
        default_input={"Input": args.input},
    )
    
    url = f"http://{args.host}:{args.port}/"
    print(f"CorrectWorkflow (sequential) on {url}  (Ctrl-C to stop)", flush=True)
    print(f"Execution mode: sequential (test first, then execute)", flush=True)
    
    if args.open:
        import webbrowser
        webbrowser.open(url)
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    main()
