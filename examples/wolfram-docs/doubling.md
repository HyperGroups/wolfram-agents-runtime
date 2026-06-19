# `doubling` — a pure Wolfram-code node

> Runtime-ized from the Wolfram **`LLMGraph`** reference page · Scope ▸ *Wolfram
> Code nodes* (input cells 15–16). Tier: **deterministic** (exact bidirectional
> value parity, fully local — no API key, no network).

A graph with a single node that runs Wolfram Language code on an input argument.
It shows that a node need not be an LLM call: a `WolframCode` node is an ordinary
deterministic function in the same dependency-inferred graph.

## Wolfram original

```wolfram
(* explicit form — cell 15 *)
LLMGraph[<|"WolframCode" -> <|"EvaluationFunction" -> (2*#Argument &),
                              "Input" -> {"Argument"}|>|>]

(* shorthand — cell 16; the slot #Argument implies Input -> {"Argument"} *)
LLMGraph[<|"WolframCode" -> (2*#Argument &)|>]
```

`#Argument` reads the input argument named `Argument`; the node returns `2 ×` it.

## This runtime (IR)

[`doubling.json`](doubling.json):

```json
{
  "nodes": {
    "WolframCode": {"wolfram": "2*deps[\"Argument\"]", "input": ["Argument"]}
  }
}
```

A `{"wolfram": "<WL>"}` node evaluates the code in a real kernel via
`wolframscript`; dependencies arrive as the association `deps`, so Wolfram's
`#Argument` becomes `deps["Argument"]`. With no node named `Argument`, the
runtime infers it as an **input argument**.

## Inferred structure

| | |
|---|---|
| nodes | `WolframCode` |
| inputs | `Argument` |
| outputs | `WolframCode` (sole sink) |
| node→node edges | *(none)* |
| kinds | `WolframCode` → `wolfram` |

## Run it

```bash
llmgraph run examples/wolfram-docs/doubling.json -i Argument=21
# -> 42

# bidirectional parity (this runtime vs native Wolfram LLMGraph), local, no key:
python tools/parity.py examples/wolfram-docs/doubling.json --input '{"Argument": 21}'
```

## Bidirectional test

Both engines evaluate the *same* WL, so the node's value is asserted **exactly
equal** across engines (not just shown).

```
STRUCTURE (exact)                  [OK] node set / outputs / edges
DETERMINISTIC NODES (exact value)  [OK] WolframCode (wolfram)   42 == 42
PARITY: PASS
```

Verified on this machine (WolframEngine 15.0), no API key or network.
