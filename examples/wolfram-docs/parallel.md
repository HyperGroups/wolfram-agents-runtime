# `parallel` — a `ListableLLMFunction` node

> Runtime-ized from the Wolfram **`LLMGraph`** reference page · Scope ▸
> *ListableLLMFunction* (input cells 12–14). Tier: **llm** — structure parity +
> side-by-side outputs (LLM output is non-deterministic).

A single node that threads one LLM call over each element of a **list** input, in
parallel. The node's output is always a list (one result per element) — the same
template, run concurrently per item.

## Wolfram original

```wolfram
parallel = LLMGraph[<|
  "NameMap" -> <|"ListableLLMFunction" -> LLMFunction["Write `Elements` in full letters:\n\n"]|>
|>];
parallel[{"1", "2", "3"}]          (* -> {"One", "Two", "Three"} — 3 concurrent calls *)
```

Internally this is an ordinary LLM node tagged `"Listable" -> True` (verified on
the kernel). Compare with a plain `"LLMFunction"` node, which submits the **whole
list** in one call and returns a single string.

## This runtime (IR)

[`parallel.json`](parallel.json):

```json
{
  "nodes": {
    "Translated": {
      "listable_llm": "Translate `words` to French. Reply with just the translation, nothing else.",
      "input": ["words"]
    }
  },
  "output": ["Translated"]
}
```

`{"listable_llm": "...", "input": [...]}` is our `ListableLLMFunction` counterpart:
the `input` deps are the list-valued arguments; the template is rendered and
submitted once per element (zipped if several lists), and the node returns the
list of results. Implemented entirely inside the node runner via `asyncio.gather`
— the graph topology is unchanged (one node, one input, one output).

## Inferred structure

| | |
|---|---|
| nodes | `Translated` |
| inputs | `words` (a list) |
| outputs | `Translated` |
| node→node edges | *(none)* |
| kinds | `Translated` → `listable_llm` |

## Run it

```bash
llmgraph run examples/wolfram-docs/parallel.json --input '{"words": ["cat", "dog", "bird"]}'
# -> ["chat", "chien", "oiseau"]  (3 concurrent LLM calls, one list result)
```

```python
from wolfram_llmgraph import load_json
load_json("examples/wolfram-docs/parallel.json")({"words": ["cat", "dog", "bird"]})
```

## Bidirectional test

LLM output is non-deterministic, so the **structure** is asserted exactly (1
`listable_llm` node, input `words`, no edges; pinned in
[`../../tests/test_wolfram_docs_examples.py`](../../tests/test_wolfram_docs_examples.py))
and the two engines' list outputs are shown side by side. Needs a shared backend.
