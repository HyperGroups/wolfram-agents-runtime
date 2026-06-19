# `output_nodes` — a deterministic DAG with two outputs

> Runtime-ized from the Wolfram **`LLMGraph`** reference page · Scope (input
> cells 21–29, the canonical `OutputNode1 / MiddleNode / OutputNode2` graph).
> Tier: **deterministic** (exact bidirectional value parity, fully local).

The reference page's running structural example: two input arguments, a node that
chains through an intermediate, and **two** output (sink) nodes. It exercises
dependency inference, fan-out, chaining, and multiple outputs — all with constant
`EvaluationFunction`s so every value is reproducible across engines.

## Wolfram original

```wolfram
LLMGraph[<|
  "OutputNode1" -> <|"Input" -> {"Arg1"},      "EvaluationFunction" -> ("Output node 1 result" &)|>,
  "MiddleNode"  -> <|"Input" -> {"Arg2"},      "EvaluationFunction" -> ("intermediate result"  &)|>,
  "OutputNode2" -> <|"Input" -> {"MiddleNode"},"EvaluationFunction" -> ("Output node 2 result" &)|>
|>]
```

`OutputNode1` and `OutputNode2` are sinks → the default outputs. `Arg1`, `Arg2`
are inputs. `MiddleNode → OutputNode2` is the only node→node edge.

## This runtime (IR)

[`output_nodes.json`](output_nodes.json):

```json
{
  "nodes": {
    "OutputNode1": {"wolfram": "\"Output node 1 result\"", "input": ["Arg1"]},
    "MiddleNode":  {"wolfram": "\"intermediate result\"",  "input": ["Arg2"]},
    "OutputNode2": {"wolfram": "\"Output node 2 result\"", "input": ["MiddleNode"]}
  },
  "output": ["OutputNode1", "OutputNode2"]
}
```

Each node returns a constant; `"input"` makes the dependency explicit (matching
the Wolfram `Input`). `output` pins both sinks, mirroring `OutputNames`.

## Inferred structure

| | |
|---|---|
| nodes | `OutputNode1`, `MiddleNode`, `OutputNode2` |
| inputs | `Arg1`, `Arg2` |
| outputs | `OutputNode1`, `OutputNode2` |
| node→node edges | `MiddleNode → OutputNode2` |
| kinds | all `wolfram` |

## Run it

```bash
llmgraph run examples/wolfram-docs/output_nodes.json -i Arg1=1 -i Arg2=2 --prop all

# intermediate override (cell 26): supplying a node's value bypasses it
llmgraph run examples/wolfram-docs/output_nodes.json \
  --input '{"OutputNode1":"custom result","Arg2":2}' --prop all

# bidirectional parity, local, no key:
python tools/parity.py examples/wolfram-docs/output_nodes.json --input '{"Arg1":1,"Arg2":2}'
```

## Bidirectional test

```
STRUCTURE (exact)                  [OK] node set / outputs / edges
DETERMINISTIC NODES (exact value)  [OK] MiddleNode  [OK] OutputNode1  [OK] OutputNode2
PARITY: PASS
```

All three node values match across engines. Verified on this machine
(WolframEngine 15.0), no API key or network.
