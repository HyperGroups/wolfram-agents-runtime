"""The ``"LLMGraph"`` property: the graph structure annotated with results,
mirroring Wolfram's ``g[input, "LLMGraph"]`` (Evaluation Properties in the docs),
including the partial form when some dependencies are unsatisfied.
"""

from wolfram_llmgraph import LLMGraph


def _docs_graph():
    # The reference page's OutputNode1 / MiddleNode / OutputNode2 structure.
    return LLMGraph(
        {
            "OutputNode1": {"fn": (lambda Arg1: "Output node 1 result"), "input": ["Arg1"]},
            "MiddleNode":  {"fn": (lambda Arg2: "intermediate result"),  "input": ["Arg2"]},
            "OutputNode2": {"fn": (lambda MiddleNode: "Output node 2 result"), "input": ["MiddleNode"]},
        },
        output=["OutputNode1", "OutputNode2"],
        llm_factory=lambda m: None,
    )


def test_llmgraph_prop_full_annotation():
    g = _docs_graph()
    res = g({"Arg1": 1, "Arg2": 2}, "LLMGraph")
    # carries the static structure...
    assert set(res["Nodes"]) == {"OutputNode1", "MiddleNode", "OutputNode2"}
    assert ("MiddleNode", "OutputNode2") in [tuple(e) for e in res["Edges"]]
    # ...annotated with every node's result, plus the supplied inputs
    assert res["Results"] == {
        "OutputNode1": "Output node 1 result",
        "MiddleNode": "intermediate result",
        "OutputNode2": "Output node 2 result",
    }
    assert res["Provided"] == {"Arg1": 1, "Arg2": 2}


def test_llmgraph_prop_partial_when_deps_unsatisfied():
    g = _docs_graph()
    # only Arg1 supplied -> only OutputNode1 is evaluable (PDF page 8)
    res = g({"Arg1": 1}, "LLMGraph")
    assert set(res["Results"]) == {"OutputNode1"}
    assert res["Results"]["OutputNode1"] == "Output node 1 result"


def test_llmgraph_prop_override_makes_downstream_evaluable():
    g = _docs_graph()
    # overriding MiddleNode satisfies OutputNode2 even without Arg2
    res = g({"Arg1": 1, "MiddleNode": "x"}, "LLMGraph")
    assert {"OutputNode1", "MiddleNode", "OutputNode2"} <= set(res["Results"])
