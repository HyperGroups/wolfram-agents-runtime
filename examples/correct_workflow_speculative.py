"""Speculative mode: execute first, then test (Wolfram semantics).

This mirrors Wolfram LLMGraph's behavior. Conditional nodes execute their
LLM/function first, then evaluate the test. If the test fails, the result
is discarded (CanceledNode).

Advantages:
- Allows parallel execution of LLM calls
- Matches Wolfram semantics exactly

Disadvantages:
- May waste LLM calls when test fails
- Higher cost when tests frequently fail
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
    """Build CorrectWorkflow in speculative mode (Wolfram semantics)."""
    
    return LLMGraph(
        {
            "Decide": "Decide if the following contains errors. Respond with either 'Correct' or 'Errors':\n\n`Input`",
            
            # In speculative mode, Review's LLM call happens first,
            # then the test checks if Decide contains "Errors"
            "Review": {
                "prompt": "List any errors in the following:\n\n`Input`",
                "test": lambda Decide: "Errors" in str(Decide),
            },
            
            # Similarly, Rewrite's LLM call happens first,
            # then the test checks if Review produced a valid string
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
        speculative=True,  # Wolfram semantics
    )


def main():
    p = argparse.ArgumentParser(description="Run CorrectWorkflow (speculative mode)")
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
    print(f"CorrectWorkflow (speculative) on {url}  (Ctrl-C to stop)", flush=True)
    print(f"Execution mode: speculative (execute first, then test)", flush=True)
    
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
