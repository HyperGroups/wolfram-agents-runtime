"""Offline structure parity for the official Wolfram ``LLMGraph`` doc examples
ported to our IR (``examples/wolfram-docs/``).

No kernel, no LLM, no network: we assert each ported graph's *static structure*
(node set, inferred inputs, outputs, node->node edges, node kinds) against the
structure of the original Wolfram example it was transcribed from. The live
cross-engine value parity (running both engines) lives in ``tools/parity.py``;
this test guards that the IR transcription itself doesn't drift.
"""

import os

import pytest

from wolfram_llmgraph import load_json

EXAMPLES = os.path.join(
    os.path.dirname(__file__), "..", "examples", "wolfram-docs"
)

# Expected static structure, transcribed from the LLMGraph reference page.
# edges are node->node (input args are not edges); sets are order-insensitive.
EXPECTED = {
    "doubling": {  # cell 15-16: WolframCode 2*#Argument
        "nodes": {"WolframCode"},
        "inputs": {"Argument"},
        "outputs": {"WolframCode"},
        "edges": set(),
        "kinds": {"WolframCode": "wolfram"},
    },
    "output_nodes": {  # cell 21-29: OutputNode1 / MiddleNode / OutputNode2
        "nodes": {"OutputNode1", "MiddleNode", "OutputNode2"},
        "inputs": {"Arg1", "Arg2"},
        "outputs": {"OutputNode1", "OutputNode2"},
        "edges": {("MiddleNode", "OutputNode2")},
        "kinds": {
            "OutputNode1": "wolfram",
            "MiddleNode": "wolfram",
            "OutputNode2": "wolfram",
        },
    },
    "conditioned": {  # cell 17-19: ConditionalNode gated by TrueQ[#NodeControl]
        "nodes": {"ConditionalNode"},
        "inputs": {"NodeControl"},
        "outputs": {"ConditionalNode"},
        "edges": set(),
        "kinds": {"ConditionalNode": "wolfram"},
    },
    "whatis": {  # cell 8-11: LLMSubmission "what is `Argument`?"
        "nodes": {"LLMSubmission"},
        "inputs": {"Argument"},
        "outputs": {"LLMSubmission"},
        "edges": set(),
        "kinds": {"LLMSubmission": "llm"},
    },
    "restyle": {  # cell 94: Haiku (LLM) -> Restyle (ToUpperCase)
        "nodes": {"Haiku", "Restyle"},
        "inputs": {"Topic"},
        "outputs": {"Restyle"},
        "edges": {("Haiku", "Restyle")},
        "kinds": {"Haiku": "llm", "Restyle": "wolfram"},
    },
    "parallel": {  # ListableLLMFunction: translate `words` in parallel
        "nodes": {"Translated"},
        "inputs": {"words"},
        "outputs": {"Translated"},
        "edges": set(),
        "kinds": {"Translated": "listable_llm"},
    },
    "summarize": {  # ListableLLMFunction + aggregation
        "nodes": {"Summaries", "Combined"},
        "inputs": {"documents"},
        "outputs": {"Combined"},
        "edges": {("Summaries", "Combined")},
        "kinds": {"Summaries": "listable_llm", "Combined": "llm"},
    },
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_ported_example_structure(name):
    g = load_json(os.path.join(EXAMPLES, f"{name}.json"))
    info = g.information()
    exp = EXPECTED[name]
    assert set(info["Nodes"]) == exp["nodes"]
    assert set(info["Inputs"]) == exp["inputs"]
    assert set(info["Outputs"]) == exp["outputs"]
    assert {tuple(e) for e in info["Edges"]} == exp["edges"]
    assert info["NodeKinds"] == exp["kinds"]
