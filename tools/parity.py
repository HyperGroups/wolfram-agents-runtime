#!/usr/bin/env python
"""Dual-engine parity harness.

Run ONE IR graph on both the thin engine (our LangGraph runtime) and the
WolframEngine native LLMGraph, then cross-validate:

  * STRUCTURE (exact): node set, node->node edges, output names.
  * DETERMINISTIC nodes (exact): values must match. (none yet — string-LLM only)
  * LLM nodes (shown, not asserted): outputs printed side by side.

Both sides use the same LLM backend (default qwen) so outputs are comparable.

Usage:
  python tools/parity.py <ir.json> [--input '{"Topic":"spring"}']
                         [--engines both|thin|wolfram] [--backend qwen]
                         [--wolframscript <path>]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from wolfram_llmgraph import load_json  # noqa: E402

DEFAULT_WOLFRAMSCRIPT = (
    r"C:\Program Files\Wolfram Research\WolframScript\wolframscript.exe"
)


def _dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def run_thin(ir_path: str, input_dict: dict, backend: str) -> dict:
    g = load_json(ir_path)
    g.backend = backend
    allres = g(input_dict, "All")
    info = g.information()
    return {
        "results": dict(allres),  # raw values (for exact compare on det nodes)
        "outputs": sorted(info["Outputs"]),
        "nodes": sorted(info["Nodes"]),
        "edges": sorted([list(e) for e in info["Edges"]]),
        "inputs": sorted(info["Inputs"]),
        "nodekinds": info["NodeKinds"],
    }


def pure_deterministic(nodekinds: dict, edges: list, inputs: list) -> set:
    """Nodes that are deterministic AND have no LLM ancestor -> exactly assertable.

    A node qualifies if its kind isn't 'llm' and every node-dependency also
    qualifies. (Input args are deterministic by definition.)
    """
    deps: dict[str, list] = {}
    for a, b in edges:  # a -> b
        deps.setdefault(b, []).append(a)
    memo: dict[str, bool] = {}

    def ok(n: str) -> bool:
        if n in memo:
            return memo[n]
        if nodekinds.get(n) == "llm":
            memo[n] = False
            return False
        memo[n] = True  # guard cycles (DAG expected)
        memo[n] = all(ok(d) for d in deps.get(n, []))
        return memo[n]

    return {n for n in nodekinds if ok(n)}


def run_wolfram(ir_path: str, input_dict: dict, wolframscript: str, backend: str, timeout: int = 120) -> dict:
    with tempfile.TemporaryDirectory() as td:
        in_path = os.path.join(td, "input.json")
        out_path = os.path.join(td, "out.json")
        with open(in_path, "w", encoding="utf-8") as fh:
            json.dump(input_dict, fh)
        try:
            proc = subprocess.run(
                [wolframscript, "-noprompt", "-file", "tools/run_native.wls", ir_path, in_path, out_path, backend],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"Wolfram native run timed out after {timeout}s. "
                "This may indicate an orphan kernel or infinite loop."
            )
        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            raise RuntimeError(
                f"wolfram run produced no output.\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
            )
        with open(out_path, encoding="utf-8") as fh:
            data = json.load(fh)
    return {
        "results": data["results"],  # native values where JSON-able
        "outputs": sorted(data["outputs"]),
        "nodes": sorted(data["nodes"]),
        "raw_edges": data["edges"],
    }


def _norm(v):
    """Normalize a value for exact cross-engine comparison."""
    return json.dumps(v, sort_keys=True, ensure_ascii=False, default=str)


def compare(thin: dict, wolfram: dict) -> bool:
    inputs = set(thin["inputs"])
    w_edges = sorted([e for e in wolfram["raw_edges"] if e[0] not in inputs])
    det = pure_deterministic(thin["nodekinds"], thin["edges"], thin["inputs"])

    ok = True
    print("=" * 64)
    print("STRUCTURE (exact)")
    for label, a, b in [
        ("node set", thin["nodes"], wolfram["nodes"]),
        ("output names", thin["outputs"], wolfram["outputs"]),
        ("node->node edges", thin["edges"], w_edges),
    ]:
        match = a == b
        ok = ok and match
        print(f"  [{'OK ' if match else 'XX '}] {label}")
        if not match:
            print(f"        thin    : {a}\n        wolfram : {b}")

    print("-" * 64)
    print("DETERMINISTIC NODES (exact value assertion)")
    det_nodes = [n for n in thin["nodes"] if n in det]
    if not det_nodes:
        print("  (none — no pure-deterministic nodes in this graph)")
    for name in det_nodes:
        t, w = thin["results"].get(name), wolfram["results"].get(name)
        match = _norm(t) == _norm(w)
        ok = ok and match
        print(f"  [{'OK ' if match else 'XX '}] {name}  ({thin['nodekinds'].get(name)})")
        if not match:
            print(f"        thin    : {t!r}\n        wolfram : {w!r}")

    print("-" * 64)
    print("LLM / NON-DETERMINISTIC NODES (shown, not asserted)")
    for name in thin["nodes"]:
        if name in det:
            continue
        t = str(thin["results"].get(name, ""))
        w = str(wolfram["results"].get(name, ""))
        print(f"\n  [{name}]")
        print(f"    thin    > {t[:240].strip()}")
        print(f"    wolfram > {w[:240].strip()}")

    print("\n" + "=" * 64)
    print(f"PARITY: {'PASS' if ok else 'FAIL'} (structure + deterministic nodes)")
    return ok


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Dual-engine parity harness.")
    p.add_argument("ir", help="IR graph JSON file")
    p.add_argument("--input", help="input args as JSON")
    p.add_argument("--engines", default="both", choices=["both", "thin", "wolfram"])
    p.add_argument("--backend", default="claude-cli", help="LLM backend for both engines")
    p.add_argument("--wolframscript", default=DEFAULT_WOLFRAMSCRIPT)
    p.add_argument("--timeout", type=int, default=120,
                   help="Timeout in seconds for Wolfram native run (default: 120)")
    args = p.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    _dotenv()
    input_dict = json.loads(args.input) if args.input else {}

    thin = wolfram = None
    if args.engines in ("both", "thin"):
        print("running thin engine (LangGraph)...", file=sys.stderr)
        thin = run_thin(args.ir, input_dict, args.backend)
    if args.engines in ("both", "wolfram"):
        print("running wolfram engine (native LLMGraph)...", file=sys.stderr)
        wolfram = run_wolfram(args.ir, input_dict, args.wolframscript, args.backend, args.timeout)

    if args.engines == "both":
        return 0 if compare(thin, wolfram) else 1

    only = thin or wolfram
    print(json.dumps(only, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
