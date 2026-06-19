"""Launch the live runtime monitor with real Qwen LLM.

需要 DASHSCOPE_API_KEY 环境变量，或在 .env 文件中设置。

    set DASHSCOPE_API_KEY=sk-xxx
    python examples/qwen_demo.py            # -> http://127.0.0.1:8765/
    python examples/qwen_demo.py --port 9000 --open
"""

from __future__ import annotations

import argparse
import os


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

from wolfram_llmgraph import LLMGraph, RunMonitor
from wolfram_llmgraph.server import serve


def build_graph(monitor):
    async def wordcount(Draft):
        return len(str(Draft).split())

    async def report(Wordcount, Sentiment):
        return f"{Wordcount} words; sentiment={Sentiment}"

    return LLMGraph(
        {
            "Draft":     "Write a short paragraph (2-3 sentences) about `Topic`",
            "Sentiment": "What is the one-word sentiment of `Topic`? Answer with just one word.",
            "Wordcount": wordcount,
            "MaybeExtra": {
                "fn": (lambda: "extra section"),
                "test": (lambda Topic: "extra" in str(Topic).lower()),
                "test_input": ["Topic"],
            },
            "Report":    report,
        },
        monitor=monitor,
        backend="qwen",
        model="qwen-plus",
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
    print(f"qwen monitor on {url}  (Ctrl-C to stop)", flush=True)
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
