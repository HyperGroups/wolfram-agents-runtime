"""Launch the live runtime monitor on a self-contained demo graph.

Fully local — no API key, no WolframEngine. A fake (delayed) LLM stands in for a
real backend so the graph runs offline, while exercising every visual feature:
parallelism, fan-in, a canceled conditional node, llm vs fn node kinds, timing.

    python examples/monitor_demo.py            # -> http://127.0.0.1:8765/
    python examples/monitor_demo.py --port 9000 --open
"""

from __future__ import annotations

import argparse
import asyncio

from wolfram_llmgraph import LLMGraph, RunMonitor
from wolfram_llmgraph.server import serve


class _FakeLLM:
    """A stand-in LLM that just echoes the prompt after a short delay."""

    def __init__(self, model, delay=0.6):
        self.model = model
        self.delay = delay

    async def ainvoke(self, prompt):
        await asyncio.sleep(self.delay)

        class _R:
            content = "(demo) " + prompt[:80]
            usage_metadata = {"input_tokens": len(prompt) // 4,
                              "output_tokens": 20, "total_tokens": len(prompt) // 4 + 20}

        return _R()


def build_graph(monitor):
    async def wordcount(Draft):           # fn node, depends on the LLM draft
        await asyncio.sleep(0.3)
        return len(str(Draft).split())

    async def report(Wordcount, Sentiment):   # fan-in of two parents
        await asyncio.sleep(0.4)
        return f"{Wordcount} words; sentiment={Sentiment}"

    return LLMGraph(
        {
            # two LLM calls fan out from the input and run concurrently:
            "Draft":     "write a short paragraph about `Topic`",
            "Sentiment": "one-word sentiment of `Topic`",
            "Wordcount": wordcount,                       # fn, depends on Draft
            "MaybeExtra": {                                # conditional -> canceled
                "fn": (lambda: "extra section"),
                "test": (lambda Topic: Topic == "__never__"),
                "test_input": ["Topic"],
            },
            "Report":    report,                          # fan-in: Wordcount + Sentiment
        },
        monitor=monitor,
        llm_factory=lambda m: _FakeLLM(m),
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--open", action="store_true")
    args = p.parse_args()

    monitor = RunMonitor()
    graph = build_graph(monitor)
    httpd, _ = serve(graph, monitor, host=args.host, port=args.port,
                     default_input={"Topic": "spring"})
    url = f"http://{args.host}:{args.port}/"
    print(f"demo monitor on {url}  (Ctrl-C to stop)", flush=True)
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
