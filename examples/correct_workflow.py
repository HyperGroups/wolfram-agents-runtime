"""Wolfram LLMGraph CorrectWorkflow example.

Original Wolfram code:

    CorrectWorkflow = LLMGraph[<|
        "Decide" -> "Decide if the following contains errors. Respond with either 'Correct' or 'Errors':\n\n`Input`",
        "Review" -> <|
            "LLMFunction" -> "List any errors in the following:\n\n`Input`",
            "TestFunction" -> Function@StringContainsQ[#Decide, "Errors"]
        |>,
        "Rewrite" -> <|
            "LLMFunction" -> "Rewrite the text to fix any issues specified in the critique:\n\n=== Text ===\n`Input`\n\n=== Critique ===\n`Review`\n",
            "TestFunction" -> Function@StringQ[#Review]
        |>,
        "Final" -> <|
            "EvaluationFunction" -> Function[
                If[StringQ[#Rewrite], 
                    "Incorrect input:\n" <> #Input <> "\nhas been rewritten as:\n" <> #Rewrite, 
                    #Input]],
            "Inputs" -> {"Rewrite", "Input"}
        |>
    |>]

This Python implementation mirrors the Wolfram structure exactly.
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


def build_correct_workflow(monitor: RunMonitor, speculative: bool = False) -> LLMGraph:
    """Build the CorrectWorkflow graph mirroring Wolfram's structure.
    
    Args:
        monitor: RunMonitor for observability
        speculative: If True, use Wolfram semantics (execute LLM first, then test).
                    If False, use sequential semantics (test first, then execute).
    """
    
    return LLMGraph(
        {
            # LLM node: decide if input has errors
            "Decide": "Decide if the following contains errors. Respond with either 'Correct' or 'Errors':\n\n`Input`",
            
            # Conditional LLM node: only runs if Decide contains "Errors"
            "Review": {
                "prompt": "List any errors in the following:\n\n`Input`",
                "test": lambda Decide: "Errors" in str(Decide),
            },
            
            # Conditional LLM node: only runs if Review produced a string
            "Rewrite": {
                "prompt": "Rewrite the following text to fix any issues specified in the critique:\n\n=== Text ===\n`Input`\n\n=== Critique ===\n`Review`\n",
                "test": lambda Review: isinstance(Review, str) and len(Review) > 0,
            },
            
            # Code node (EvaluationFunction): format final output
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
        speculative=speculative,
    )


def main():
    p = argparse.ArgumentParser(description="Run CorrectWorkflow example")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--open", action="store_true")
    p.add_argument("--input", default="The quik brown fox jump over the lazy dog.",
                   help="Input text to check")
    p.add_argument("--speculative", action="store_true",
                   help="Use Wolfram semantics: execute LLM first, then test")
    args = p.parse_args()
    
    monitor = RunMonitor()
    graph = build_correct_workflow(monitor, speculative=args.speculative)
    
    mode = "speculative (Wolfram)" if args.speculative else "sequential"
    print(f"Execution mode: {mode}", flush=True)
    
    httpd, _ = serve(
        graph, monitor,
        host=args.host, port=args.port,
        default_input={"Input": args.input},
    )
    
    url = f"http://{args.host}:{args.port}/"
    print(f"CorrectWorkflow monitor on {url}  (Ctrl-C to stop)", flush=True)
    print(f"Default input: {args.input!r}", flush=True)
    
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
