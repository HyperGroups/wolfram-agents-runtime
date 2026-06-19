# `restyle` — an LLM node feeding a Wolfram-code transform

> Runtime-ized from the Wolfram **`LLMGraph`** reference page · Applications
> (input cell 94). Tier: **llm** (structure parity exact; the transformed value
> depends on the non-deterministic `Haiku` node, so it is shown, not asserted).

A mixed graph: an LLM writes a haiku, then a deterministic Wolfram-code node
post-processes it. This is the common "LLM produces text → code reshapes it"
pattern, in one dependency-inferred graph.

## Wolfram original

```wolfram
poem = LLMGraph[<|
  "Haiku"   -> "write a haiku about `Topic`",
  "Restyle" -> (ToUpperCase[#Haiku] &)
|>];
poem["winter"]
```

`Restyle` references `#Haiku`, so it depends on the `Haiku` node; `` `Topic` `` is
an input argument. `Restyle` is the sole sink → the output.

## This runtime (IR)

[`restyle.json`](restyle.json):

```json
{
  "nodes": {
    "Haiku":   "write a haiku about `Topic`",
    "Restyle": {"wolfram": "ToUpperCase[deps[\"Haiku\"]]", "input": ["Haiku"]}
  }
}
```

`Haiku` is a string-LLM node; `Restyle` is a `wolfram` code node reading its
parent's output as `deps["Haiku"]`. The runtime infers `Haiku → Restyle` from the
dependency and `Topic` as the lone input.

## Inferred structure

| | |
|---|---|
| nodes | `Haiku`, `Restyle` |
| inputs | `Topic` |
| outputs | `Restyle` |
| node→node edges | `Haiku → Restyle` |
| kinds | `Haiku` → `llm`, `Restyle` → `wolfram` |

## Run it

```bash
llmgraph run examples/wolfram-docs/restyle.json -i Topic=winter --prop all

# bidirectional parity (shared backend on both engines):
python tools/parity.py examples/wolfram-docs/restyle.json \
  --input '{"Topic":"winter"}' --backend claude-cli
```

## Bidirectional test

The **structure** is asserted exactly (`Haiku → Restyle`, output `Restyle`,
input `Topic`). `Restyle`'s value is a deterministic function *of an LLM output*,
which differs per run and per engine, so it is shown rather than asserted. Run via
`tools/parity_sweep.py --only restyle`.
