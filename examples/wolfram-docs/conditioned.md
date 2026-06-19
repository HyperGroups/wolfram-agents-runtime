# `conditioned` — a conditional node (`ConditionalNode`)

> Runtime-ized from the Wolfram **`LLMGraph`** reference page · Scope ▸
> *Conditional nodes* (input cells 17–19). Tier: **deterministic** (exact
> bidirectional value parity on both branches, fully local — no key, no network).

A node that only evaluates when a **test** predicate over its inputs is true. When
the test fails the node is *skipped* but still appears in the results, carrying a
canceled sentinel (Wolfram `Missing["CanceledNode", name]`).

## Wolfram original

```wolfram
conditioned = LLMGraph[<|
  "ConditionalNode" -> <|
    "EvaluationFunction"  -> (Success["NodeHasRun", <||>] &),
    "TestFunction"        -> (TrueQ[#NodeControl] &),
    "InputTestFunction"   -> {"NodeControl"}
  |>
|>];

conditioned[<|"NodeControl" -> True|>]   (* -> the node runs            *)
conditioned[<|"NodeControl" -> False|>]  (* -> Missing["CanceledNode", "ConditionalNode"] *)
```

`InputTestFunction` declares the inputs the `TestFunction` reads — they become
graph inputs of the node even though the `EvaluationFunction` ignores them.

## This runtime (IR)

[`conditioned.json`](conditioned.json):

```json
{
  "nodes": {
    "ConditionalNode": {
      "wolfram": "\"NodeHasRun\"",
      "test": "TrueQ[deps[\"NodeControl\"]]",
      "test_input": ["NodeControl"]
    }
  }
}
```

Any mapping node-spec may add a `test` (a WL code string, or a Python callable via
the API) plus `test_input` (its arguments — Wolfram's `InputTestFunction`). The
test's inputs and the evaluation's inputs are tracked separately: only eval deps
feed the `EvaluationFunction`, but **both** wire the graph (scheduling / inputs /
edges). When the test is falsy the node yields `CanceledNode` →
`Missing[CanceledNode, ConditionalNode]`.

```python
from wolfram_llmgraph import LLMGraph, is_canceled
g = LLMGraph({"Cond": {"fn": (lambda: "ran"),
                       "test": (lambda Ctrl: bool(Ctrl)), "test_input": ["Ctrl"]}})
is_canceled(g({"Ctrl": False}, "All")["Cond"])   # True
```

## Inferred structure

| | |
|---|---|
| nodes | `ConditionalNode` |
| inputs | `NodeControl` (from `test_input`) |
| outputs | `ConditionalNode` |
| node→node edges | *(none)* — a `test_input` that names another node would add one |
| kinds | `ConditionalNode` → `wolfram` |

## Run it

```bash
llmgraph run examples/wolfram-docs/conditioned.json -i NodeControl=true
# -> NodeHasRun

# bidirectional parity (both branches), local, no key:
python tools/parity.py examples/wolfram-docs/conditioned.json --input '{"NodeControl": true}'
python tools/parity.py examples/wolfram-docs/conditioned.json --input '{"NodeControl": false}'
```

Note: the CLI `-i NodeControl=true` passes the *string* `"true"` (truthy); use
`--input '{"NodeControl": true}'` for a real JSON boolean.

## Bidirectional test

Both branches are deterministic, so values are asserted **exactly equal** across
engines:

```
NodeControl = true   ->  ConditionalNode == "NodeHasRun"                  PARITY: PASS
NodeControl = false  ->  ConditionalNode == Missing[CanceledNode, ...]    PARITY: PASS
```

Verified on this machine (WolframEngine 15.0), no API key or network. The
`CanceledNode` sentinel renders to the same text Wolfram exports for the canceled
node, so the false branch matches by value too.

## Known divergence

If a **downstream node depends on a canceled node**, native `LLMGraph` was observed
to hang (the canceled value doesn't cleanly propagate). This example keeps the
conditional node a sink to stay within well-defined territory; downstream-of-
canceled semantics are left unspecified until reconciled.
