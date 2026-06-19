#!/usr/bin/env python
"""Bidirectional parity sweep over the official Wolfram ``LLMGraph`` doc examples
ported to our IR (``examples/wolfram-docs/`` + the root ``bestpoem``/``renga``).

For each example it runs the SAME IR on both engines — our thin LangGraph runtime
and the WolframEngine native ``LLMGraph`` — and cross-validates (see tools/parity.py):

  * STRUCTURE (exact): node set, node->node edges, output names.
  * DETERMINISTIC nodes (exact): Wolfram-code node values must match.
  * LLM nodes: shown side by side, not asserted.

Two tiers:
  * ``det``  — pure Wolfram-code graphs. Exact value parity, runs fully LOCAL
               (a wolframscript kernel on each side; no API key, no network).
  * ``llm``  — graphs with string-LLM nodes. Structure parity + side-by-side
               outputs; needs a shared LLM backend (default claude-cli). Skipped
               unless ``--with-llm`` is given.

Usage:
  python tools/parity_sweep.py                      # deterministic tier only (local)
  python tools/parity_sweep.py --with-llm           # also the LLM examples
  python tools/parity_sweep.py --with-llm --backend qwen
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import parity  # noqa: E402  (run_thin / run_wolfram / compare / _dotenv)

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..")

# name, IR path (relative to project root), input args, tier.
CATALOG = [
    ("doubling",     "examples/wolfram-docs/doubling.json",     {"Argument": 21},         "det"),
    ("output_nodes", "examples/wolfram-docs/output_nodes.json", {"Arg1": 1, "Arg2": 2},   "det"),
    ("conditioned",  "examples/wolfram-docs/conditioned.json",  {"NodeControl": True},    "det"),
    ("whatis",       "examples/wolfram-docs/whatis.json",       {"Argument": "helium"},   "llm"),
    ("restyle",      "examples/wolfram-docs/restyle.json",      {"Topic": "winter"},      "llm"),
    ("bestpoem",     "examples/bestpoem.json",                  {},                       "llm"),
    ("renga",        "examples/renga.json",                     {"Topic": "spring"},      "llm"),
]


def run_one(name: str, ir: str, inp: dict, backend: str, wolframscript: str, timeout: int = 120) -> bool:
    print("\n" + "#" * 64)
    print(f"# {name}   ({ir})   input={inp}")
    print("#" * 64)
    thin = parity.run_thin(ir, inp, backend)
    wolfram = parity.run_wolfram(ir, inp, wolframscript, backend, timeout)
    return parity.compare(thin, wolfram)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--with-llm", action="store_true", help="also run the LLM-tier examples")
    p.add_argument("--backend", default="claude-cli", help="shared LLM backend for the llm tier")
    p.add_argument("--wolframscript", default=parity.DEFAULT_WOLFRAMSCRIPT)
    p.add_argument("--timeout", type=int, default=120,
                   help="Timeout in seconds for each Wolfram native run (default: 120)")
    p.add_argument("--only", help="run a single example by name")
    args = p.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    # parity.py expects to run from the project root (relative IR/script paths).
    os.chdir(os.path.abspath(ROOT))
    parity._dotenv()

    results: list[tuple[str, str, str]] = []  # name, tier, status
    for name, ir, inp, tier in CATALOG:
        if args.only and name != args.only:
            continue
        if tier == "llm" and not args.with_llm and not args.only:
            results.append((name, tier, "SKIP (no --with-llm)"))
            continue
        backend = args.backend
        try:
            ok = run_one(name, ir, inp, backend, args.wolframscript, args.timeout)
            results.append((name, tier, "PASS" if ok else "FAIL"))
        except Exception as exc:  # keep sweeping; report per-example
            results.append((name, tier, f"ERROR: {str(exc)[:80]}"))

    print("\n" + "=" * 64)
    print("SWEEP SUMMARY")
    print("=" * 64)
    width = max(len(n) for n, _, _ in results) if results else 8
    for name, tier, status in results:
        print(f"  {name:<{width}}  [{tier}]  {status}")
    failed = [r for r in results if r[2] not in ("PASS",) and not r[2].startswith("SKIP")]
    print("=" * 64)
    print(f"{len(results)} run, {sum(s=='PASS' for _,_,s in results)} pass, "
          f"{len(failed)} not-pass, "
          f"{sum(s.startswith('SKIP') for _,_,s in results)} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
