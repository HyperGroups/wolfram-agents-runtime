"""``agents`` — the umbrella CLI for the Wolfram-style LLM/agents runtime.

This lives in the **`wolfram_agents`** package (the system umbrella), separate
from the **`wolfram_llmgraph`** library it composes: a system can have multiple
packages — ``wolfram_llmgraph`` is the LLMGraph library; ``wolfram_agents`` is the
agents-first entry point that groups the LLM family (mirroring Wolfram's
*LLM-Related Functionality* guide):

    wolfram_agents do "<task>"            NL task → planned LLMGraph → result
                                          (the LLMGraph is saved to graphs/<slug>.json
                                           + .wls — open the .wls in Mathematica)
    wolfram_agents synthesize "<prompt>"  LLMSynthesize — one-shot generation
    wolfram_agents graph run|info|serve … LLMGraph / LLMGraphSubmit (= the llmgraph CLI)
    wolfram_agents prompt list|show <name> LLMPrompt — the prompt library
    wolfram_agents backends               available LLM backends + credential status
    wolfram_agents doctor [--fix] [--json] environment self-check / guided setup

Installed as ``wolfram_agents`` (and ``wolfram-agents``); ``llmgraph`` is the
graph-only entry (≡ ``wolfram_agents graph``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from wolfram_llmgraph.backends import BACKENDS


def _setup_io() -> None:
    from wolfram_llmgraph import cli as lg_cli

    lg_cli._load_dotenv()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def _save_planned_graph(ir: dict, args: argparse.Namespace) -> None:
    """Persist the planned LLMGraph as <base>.json + <base>.wls (Wolfram).

    A `do` task is a workflow — an LLMGraph structure, not just LangGraph
    plumbing — so by default we write it to disk. The .wls form opens in
    Mathematica and runs on a real kernel; the .json runs on our runtime.
    Disabled by --no-save; the one-shot `synthesize` never saves.
    """
    from wolfram_llmgraph.wolfram_export import save_graph, slugify

    base = args.save_graph or os.path.join("graphs", slugify(args.task))
    paths = save_graph(ir, base, task=args.task)
    print(f"saved LLMGraph -> {paths['json']}  (+ {paths['wls']} for Mathematica)",
          file=sys.stderr)


def _cmd_do(args: argparse.Namespace) -> int:
    from wolfram_llmgraph.backends import resolve_backend
    from wolfram_llmgraph.planner import plan_graph, run_task

    backend = resolve_backend(args.backend or os.environ.get("LLMGRAPH_BACKEND"),
                              strict=args.backend_strict)
    print(f"using backend: {backend}", file=sys.stderr)
    if args.plan_only:
        ir = plan_graph(args.task, backend=backend, model=args.model, retries=args.retries)
        if not args.no_save:
            _save_planned_graph(ir, args)
        print(json.dumps(ir, indent=2, ensure_ascii=False))
        return 0
    prop = "All" if args.prop in ("all", "All") else None
    ir, result = run_task(args.task, backend=backend, model=args.model,
                          prop=prop, retries=args.retries)
    if not args.no_save:
        _save_planned_graph(ir, args)
    if args.show_graph:
        print("--- planned LLMGraph ---", file=sys.stderr)
        print(json.dumps(ir, indent=2, ensure_ascii=False), file=sys.stderr)
        print("--- result ---", file=sys.stderr)
    if isinstance(result, (dict, list)):
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        print(result)
    return 0


def _cmd_synthesize(args: argparse.Namespace) -> int:
    from wolfram_llmgraph.backends import resolve_backend
    from wolfram_llmgraph.synthesize import LLMSynthesize

    backend = resolve_backend(args.backend or os.environ.get("LLMGRAPH_BACKEND"),
                              strict=args.backend_strict)
    print(f"using backend: {backend}", file=sys.stderr)
    text = sys.stdin.read() if args.prompt == "-" else args.prompt
    print(LLMSynthesize(text, backend=backend, model=args.model))
    return 0


def _cmd_graph(args: argparse.Namespace) -> int:
    from wolfram_llmgraph import cli as lg_cli

    return lg_cli.main(args.args)


def _cmd_prompt(args: argparse.Namespace) -> int:
    from wolfram_llmgraph.prompts import default_library

    lib = default_library()
    if args.action == "list":
        for name in lib.names():
            print(name)
        return 0
    if not args.name:
        print("error: `prompt show` needs a name", file=sys.stderr)
        return 1
    try:
        print(lib.resolve(args.name))
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_backends(args: argparse.Namespace) -> int:
    from wolfram_llmgraph.doctor import diagnose

    rep = diagnose()
    if args.json:
        print(json.dumps(rep["backends"], indent=2, ensure_ascii=False))
    else:
        for b in rep["backends"]:
            print(f"  {'OK ' if b['available'] else '-- '} {b['name']:<14} {b['detail']}")
        print(f"\nauto -> {rep['default_backend'] or '(none usable — run `wolfram_agents doctor --fix`)'}")
    return 0 if rep["usable"] else 1


def _cmd_doctor(args: argparse.Namespace) -> int:
    from wolfram_llmgraph.cli import _cmd_doctor as cli_doctor

    return cli_doctor(args)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wolfram_agents",
        description="Wolfram-style LLM/agents runtime — the LLM family as one CLI.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    do = sub.add_parser("do", help="natural-language task → planned LLMGraph → result")
    do.add_argument("task", help="the task in natural language")
    do.add_argument("--show-graph", action="store_true",
                    help="print the planned LLMGraph (to stderr) before the result")
    do.add_argument("--plan-only", action="store_true",
                    help="only plan the graph (print the IR), don't run it")
    do.add_argument("--save-graph", metavar="BASE",
                    help="where to save the planned LLMGraph (BASE.json + BASE.wls); "
                         "default: graphs/<task-slug>")
    do.add_argument("--no-save", action="store_true",
                    help="don't persist the planned LLMGraph to disk")
    do.add_argument("--prop", default="auto", help="auto (outputs) | all (every node)")
    do.add_argument("--retries", type=int, default=2,
                    help="self-repair attempts if the planned graph is invalid (default 2)")
    do.add_argument("--backend", choices=["auto", *BACKENDS],
                    help="LLM backend ('auto' detects; falls back to $LLMGRAPH_BACKEND)")
    do.add_argument("--backend-strict", action="store_true")
    do.add_argument("--model", help="override the model")
    do.set_defaults(func=_cmd_do)

    syn = sub.add_parser("synthesize", help="LLMSynthesize — one-shot text generation")
    syn.add_argument("prompt", help="prompt text (or '-' to read stdin)")
    syn.add_argument("--backend", choices=["auto", *BACKENDS],
                     help="LLM backend ('auto' detects; falls back to $LLMGRAPH_BACKEND)")
    syn.add_argument("--backend-strict", action="store_true",
                     help="use exactly the specified backend, fail if missing")
    syn.add_argument("--model", help="override the model")
    syn.set_defaults(func=_cmd_synthesize)

    g = sub.add_parser("graph", help="LLMGraph / LLMGraphSubmit (= the llmgraph CLI)")
    g.add_argument("args", nargs=argparse.REMAINDER,
                   help="run | info | serve | doctor … (forwarded to llmgraph)")
    g.set_defaults(func=_cmd_graph)

    pr = sub.add_parser("prompt", help="LLMPrompt — the prompt library")
    pr.add_argument("action", choices=["list", "show"])
    pr.add_argument("name", nargs="?", help="prompt name (for `show`)")
    pr.set_defaults(func=_cmd_prompt)

    bk = sub.add_parser("backends", help="list LLM backends + credential status")
    bk.add_argument("--json", action="store_true")
    bk.set_defaults(func=_cmd_backends)

    dc = sub.add_parser("doctor", help="environment self-check / guided setup")
    dc.add_argument("--json", action="store_true")
    dc.add_argument("--fix", action="store_true")
    dc.set_defaults(func=_cmd_doctor)

    return p


def main(argv: list[str] | None = None) -> int:
    _setup_io()
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    try:
        return args.func(args)
    except Exception as exc:  # clean error on the CLI
        _print_cli_error(exc)
        return 1


def _print_cli_error(exc: Exception) -> None:
    msg = str(exc)
    print(f"error: {msg}", file=sys.stderr)
    low = msg.lower()
    if "connection" in low or "timed out" in low or "timeout" in low:
        print("hint: that LLM backend couldn't reach the service. Retry; check your "
              "connection; or switch backend — e.g. `--backend claude-cli`, or set "
              "LLMGRAPH_BACKEND=claude-cli (in .env). See `wolfram_agents doctor`.",
              file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
