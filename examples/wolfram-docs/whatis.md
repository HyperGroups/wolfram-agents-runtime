# `whatis` — a single LLM node (the `LLMSubmission` forms)

> Runtime-ized from the Wolfram **`LLMGraph`** reference page · Scope ▸
> *LLMSubmission* (input cells 8–11). Tier: **llm** (structure parity exact; LLM
> output shown side by side, not asserted).

The simplest possible graph: one LLM node taking one input argument. The doc shows
four equivalent spellings of the same node — all collapse to a single string-LLM
node in this runtime.

## Wolfram original

```wolfram
(* all four are equivalent — cells 8, 9, 10, 11 *)
LLMGraph[<|"LLMSubmission" -> <|"LLMFunction" -> LLMFunction["what is `Argument`?"],
                                "Input" -> {"Argument"}|>|>]
LLMGraph[<|"LLMSubmission" -> LLMFunction["what is `Argument`?"]|>]
LLMGraph[<|"LLMSubmission" -> StringTemplate["what is `Argument`?"]|>]
LLMGraph[<|"LLMSubmission" -> "what is `Argument`?"|>]
```

The `` `Argument` `` slot has no matching node, so it is an input argument.

## This runtime (IR)

[`whatis.json`](whatis.json):

```json
{
  "nodes": {
    "LLMSubmission": "what is `Argument`?"
  }
}
```

A bare prompt string is an LLM node; its `` `Slot` `` references become
dependencies (here, the input `Argument`). The `LLMFunction` / `StringTemplate`
wrappers in the Wolfram original carry no extra structure for this graph, so the
plain-string form is the faithful transcription.

## Inferred structure

| | |
|---|---|
| nodes | `LLMSubmission` |
| inputs | `Argument` |
| outputs | `LLMSubmission` |
| node→node edges | *(none)* |
| kinds | `LLMSubmission` → `llm` |

## Run it

```bash
llmgraph run examples/wolfram-docs/whatis.json -i Argument=helium

# bidirectional parity (shared backend on both engines):
python tools/parity.py examples/wolfram-docs/whatis.json \
  --input '{"Argument":"helium"}' --backend claude-cli
```

## Bidirectional test

LLM output is non-deterministic, so the **structure** is asserted exactly (1 node,
1 input, no edges) and the two engines' answers are printed side by side for
inspection. Needs a shared LLM backend; run via `tools/parity_sweep.py --only whatis`.
