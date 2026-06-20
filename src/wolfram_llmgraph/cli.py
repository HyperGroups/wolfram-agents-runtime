"""Command-line interface for the LLMGraph runtime.

Examples::

    llmgraph run examples/bestpoem.json
    llmgraph run examples/renga.json --input '{"Topic": "spring"}'
    llmgraph run examples/renga.json -i Topic=autumn --prop all
    llmgraph info examples/renga.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .backends import BACKENDS
from .loaders import load_json


def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader: set KEY=VALUE lines not already in the environment."""
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


def _parse_input(input_json: str | None, kv: list[str] | None) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if input_json:
        src = input_json
        if input_json.startswith("@"):
            with open(input_json[1:], "r", encoding="utf-8") as fh:
                src = fh.read()
        data.update(json.loads(src))
    for pair in kv or []:
        if "=" not in pair:
            raise SystemExit(f"--input-kv expects key=value, got: {pair!r}")
        key, val = pair.split("=", 1)
        data[key] = val
    return data


def _parse_prop(s: str | None) -> Any:
    """Map the ``--prop`` string to a graph property selector.

    ``auto`` -> None (output nodes); ``all`` -> "All"; ``Graph`` -> structure;
    ``LLMGraph`` -> structure annotated with results; ``a,b`` -> a list of node
    names; anything else -> a single node name.
    """
    if s is None or s in ("auto", "Automatic", "automatic"):
        return None
    if s in ("all", "All"):
        return "All"
    if s in ("Graph", "graph"):
        return "Graph"
    if s in ("LLMGraph", "llmgraph"):
        return "LLMGraph"
    if "," in s:
        return [part.strip() for part in s.split(",") if part.strip()]
    return s


def _cmd_run(args: argparse.Namespace) -> int:
    graph = load_json(args.file, backend_strict=args.backend_strict)
    if args.model:
        graph.model = args.model
    backend = args.backend or os.environ.get("LLMGRAPH_BACKEND")
    if backend:
        from .backends import resolve_backend
        graph.backend = resolve_backend(backend, strict=args.backend_strict)
    inp = _parse_input(args.input, args.input_kv)
    prop = _parse_prop(args.prop)
    result = graph(inp, prop)

    if isinstance(result, (dict, list)):
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        print(result)
    return 0


def _cmd_info(args: argparse.Namespace) -> int:
    graph = load_json(args.file, backend_strict=args.backend_strict)
    info = graph.information()
    print(json.dumps(info, indent=2, ensure_ascii=False, default=str))
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    from .doctor import diagnose, fix, format_report

    rep = diagnose()
    if args.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print(format_report(rep))
    if getattr(args, "fix", False):
        print("\n--- fix ---")
        for action in fix(rep):
            print(f"  • {action}")
        rep = diagnose()  # re-check after fixing
    # exit non-zero when no backend is usable, so scripts/agents can branch on it
    return 0 if rep["usable"] else 1


def _cmd_serve(args: argparse.Namespace) -> int:
    from .monitor import RunMonitor
    from .server import serve

    graph = load_json(args.file, backend_strict=args.backend_strict)
    if args.model:
        graph.model = args.model
    backend = args.backend or os.environ.get("LLMGRAPH_BACKEND")
    if backend:
        from .backends import resolve_backend
        graph.backend = resolve_backend(backend, strict=args.backend_strict)
    print(f"using backend: {graph.backend}", file=sys.stderr)
    monitor = RunMonitor()
    graph.monitor = monitor
    default_input = _parse_input(args.input, args.input_kv)

    httpd, _app = serve(
        graph, monitor, host=args.host, port=args.port,
        default_input=default_input, prop="All",
    )
    url = f"http://{args.host}:{args.port}/"
    print(f"llmgraph monitor on {url}  (Ctrl-C to stop)", file=sys.stderr)
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="llmgraph",
        description="Run Wolfram-style LLMGraphs on LangGraph.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Evaluate a graph")
    run.add_argument("file", help="JSON graph file (or raw JSON string)")
    run.add_argument(
        "--input",
        help="Input as JSON, or @path.json to read from a file",
    )
    run.add_argument(
        "-i",
        "--input-kv",
        action="append",
        metavar="KEY=VALUE",
        help="Set one input argument (repeatable)",
    )
    run.add_argument(
        "--prop",
        default="auto",
        metavar="SELECTOR",
        help=(
            "auto = output nodes (default); all = every node's result; "
            "Graph = graph structure; a node name = just that node; "
            "comma-separated names = those nodes"
        ),
    )
    run.add_argument("--model", help="Override the graph-wide default model")
    run.add_argument(
        "--backend",
        choices=["auto", *BACKENDS],
        help=(
            "LLM backend: 'auto' (default) detects available credentials; "
            "or specify: anthropic, claude-cli, qwen, qwen-tokenplan, openai, deepseek. "
            "Falls back to $LLMGRAPH_BACKEND."
        ),
    )
    run.add_argument(
        "--backend-strict",
        action="store_true",
        help="Manual mode: use exactly the specified backend, fail if credentials missing",
    )
    run.set_defaults(func=_cmd_run)

    info = sub.add_parser("info", help="Show a graph's nodes, inputs and edges")
    info.add_argument("file", help="JSON graph file (or raw JSON string)")
    info.add_argument(
        "--backend-strict",
        action="store_true",
        help="Manual mode: use exactly the specified backend",
    )
    info.set_defaults(func=_cmd_info)

    srv = sub.add_parser("serve", help="Launch the live runtime monitor web app")
    srv.add_argument("file", help="JSON graph file (or raw JSON string)")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8765)
    srv.add_argument("--open", action="store_true", help="open a browser window")
    srv.add_argument("--input", help="default input as JSON, or @path.json")
    srv.add_argument("-i", "--input-kv", action="append", metavar="KEY=VALUE",
                     help="set one default input argument (repeatable)")
    srv.add_argument("--model", help="override the graph-wide default model")
    srv.add_argument(
        "--backend",
        choices=["auto", *BACKENDS],
        help=(
            "LLM backend: 'auto' (default) detects available credentials; "
            "or specify: anthropic, claude-cli, qwen, qwen-tokenplan, openai, deepseek"
        ),
    )
    srv.add_argument(
        "--backend-strict",
        action="store_true",
        help="Manual mode: use exactly the specified backend, fail if credentials missing",
    )
    srv.set_defaults(func=_cmd_serve)

    doc = sub.add_parser(
        "doctor", help="Check the environment: backends, credentials, tools")
    doc.add_argument("--json", action="store_true", help="emit the report as JSON")
    doc.add_argument("--fix", action="store_true",
                     help="guided setup: create .env, suggest/enter a key")
    doc.set_defaults(func=_cmd_doctor)

    return p


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    # Claude output is UTF-8; avoid mojibake on consoles with a legacy codepage.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    try:
        return args.func(args)
    except Exception as exc:  # surface a clean error on the CLI
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
