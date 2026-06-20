# `summarize` — map-reduce over documents (`ListableLLMFunction` + aggregate)

> Runtime-ized from the Wolfram **`LLMGraph`** reference page · Applications ▸
> *Summarization* (input cells 108–112). Tier: **llm** — structure parity +
> side-by-side outputs.

The canonical map-reduce pattern: summarize each document **in parallel** with a
`ListableLLMFunction` node, then a second LLM node **combines** the per-document
summaries into one. Accommodates an LLM's limited attention window by chunking the
work across concurrent calls.

## Wolfram original

```wolfram
summarize = LLMGraph[<|
  "Chunk"        -> <|"EvaluationFunction" -> (StringPartition[#Text, UpTo[12000]] &), "Input" -> {"Text"}|>,
  "ChunkSummary" -> <|"ListableLLMFunction" -> "Summarize the following part in a few lines:\n\n`Chunk`"|>,
  "FinalSummary" -> "Summarize the following:\n\n`ChunkSummary`"
|>];
summarize[<|"Text" -> ExampleData[{"Text", "USConstitution"}]|>]
```

(The chunking step is an `EvaluationFunction`; our port takes a pre-split list of
documents directly, keeping the map-reduce shape.)

## This runtime (IR)

[`summarize.json`](summarize.json):

```json
{
  "nodes": {
    "Summaries": {
      "listable_llm": "Summarize this text in one sentence: `documents`",
      "input": ["documents"]
    },
    "Combined": "Combine these summaries into a single coherent summary:\n\n`Summaries`"
  },
  "output": ["Combined"]
}
```

`Summaries` is a `listable_llm` node — it maps the one-sentence-summary prompt over
each element of the `documents` list, concurrently, producing a list. `Combined` is
a plain LLM node that depends on `Summaries` (the list is rendered into its prompt)
and reduces them to a single summary.

## Inferred structure

| | |
|---|---|
| nodes | `Summaries`, `Combined` |
| inputs | `documents` (a list) |
| outputs | `Combined` |
| node→node edges | `Summaries → Combined` |
| kinds | `Summaries` → `listable_llm`, `Combined` → `llm` |

## Run it

```bash
llmgraph run examples/wolfram-docs/summarize.json \
  --input '{"documents": ["Long text A …", "Long text B …", "Long text C …"]}'
```

## Bidirectional test

The **structure** is asserted exactly (`Summaries → Combined`, output `Combined`,
input `documents`; pinned in
[`../../tests/test_wolfram_docs_examples.py`](../../tests/test_wolfram_docs_examples.py)).
The map step's list and the final reduced summary are LLM-generated, so they are
shown rather than asserted. Needs a shared backend.
