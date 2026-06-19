# Official `LLMGraph` doc examples, runtime-ized

These are the canonical examples from Wolfram's own **`LLMGraph`** reference page
(`Documentation.en-us/15.0/.../ReferencePages/Symbols/LLMGraph.nb`, extracted from
the live 15.0 kernel), transcribed into this runtime's JSON IR so the **same graph
runs on both engines** — our thin LangGraph runtime and the WolframEngine native
`LLMGraph` — and is cross-validated (bidirectional / 双向测试).

Each example is self-contained: an IR file (`<name>.json`) **and** its own
documentation page (`<name>.md`, a mini reference page — source cell, Wolfram
original, our IR, inferred structure, how to run, parity result).

| example | page | source cell | what it shows | tier |
|---------|------|-------------|---------------|------|
| `doubling` | [doubling.md](doubling.md) · [.json](doubling.json) | Scope, "Wolfram Code nodes" (15–16) | a pure `WolframCode` node `2*#Argument` | **det** — exact value parity, local |
| `output_nodes` | [output_nodes.md](output_nodes.md) · [.json](output_nodes.json) | Scope (21–29) | the `OutputNode1 / MiddleNode / OutputNode2` DAG: inputs, fan-out, chaining, two outputs | **det** — exact value parity, local |
| `conditioned` | [conditioned.md](conditioned.md) · [.json](conditioned.json) | Scope, "Conditional nodes" (17–19) | a `ConditionalNode` gated by `TrueQ[#NodeControl]`; skipped → `Missing[CanceledNode, …]` | **det** — exact value parity (both branches), local |
| `whatis` | [whatis.md](whatis.md) · [.json](whatis.json) | Scope, `LLMSubmission` forms (8–11) | a single LLM node `"what is \`Argument\`?"` (the `LLMFunction` / `StringTemplate` / string forms all collapse to this) | llm — structure parity |
| `restyle` | [restyle.md](restyle.md) · [.json](restyle.json) | Applications (94) | LLM node `Haiku` feeding a deterministic `ToUpperCase` Wolfram-code node `Restyle` | llm — structure parity |

The classic `bestpoem` (Poet1/Poet2/Judge) and `renga` (haiku/complete) examples
— also straight from this doc page — live one level up in [`../bestpoem.json`](../bestpoem.json)
and [`../renga.json`](../renga.json).

## Tiers

* **det** (deterministic): graphs made of Wolfram-code nodes only. Both engines
  evaluate the *same WL* (the thin runtime shells `wolframscript`; native runs it
  in-kernel), so every node's value is asserted **exactly equal** across engines.
  Needs only a local WolframEngine — **no API key, no network.**
* **llm**: graphs with string-LLM nodes. LLM output is non-deterministic, so we
  assert the **structure** exactly (node set / edges / outputs) and show the two
  engines' outputs side by side. Needs a shared LLM backend on both sides.

## Run the bidirectional tests

```bash
# Deterministic tier only — fully local, exact value parity, no key:
python tools/parity_sweep.py

# Include the LLM examples (shared backend on both engines):
python tools/parity_sweep.py --with-llm --backend claude-cli

# A single example, either tier:
python tools/parity_sweep.py --only renga
python tools/parity.py examples/wolfram-docs/doubling.json --input '{"Argument":21}'
```

Static structure (no kernel, no LLM) is also pinned in
[`../../tests/test_wolfram_docs_examples.py`](../../tests/test_wolfram_docs_examples.py)
so the IR transcription can't silently drift from the doc.

## Recently implemented

The following features were previously gaps but are now supported:

* **`ListableLLMFunction`** map nodes — `parallel` (12) and the map-reduce
  `summarize` (108) examples. See [`parallel.json`](parallel.json) and
  [`summarize.json`](summarize.json). (Implemented in P0-1.)
* **`$Failed` propagation** — Wolfram threads `$Failed` through dependents;
  our `wolfram` compute node now returns `FailedNode` instead of raising, and
  downstream nodes automatically propagate the failure. (Implemented in P0-2.)

`ConditionalNode` (cells 17–19) **is** supported — see
[`conditioned.md`](conditioned.md).
