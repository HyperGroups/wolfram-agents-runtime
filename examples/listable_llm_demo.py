"""ListableLLMFunction demo: parallel LLM calls over list inputs.

This example shows how to use the `listable_llm` node type to map an LLM
call over each element of a list input in parallel. This is the runtime
analog of Wolfram's `ListableLLMFunction`.

Run with a real key:
    export ANTHROPIC_API_KEY=sk-ant-...
    python examples/listable_llm_demo.py
"""

from wolfram_llmgraph import LLMGraph


graph = LLMGraph(
    {
        # ListableLLMFunction: maps the LLM call over each element in `items`
        # Each item gets its own LLM call in parallel
        "translated": {
            "listable_llm": "Translate `items` to French. Reply with just the translation.",
            "input": ["items"],
        },
        # Regular LLM node that depends on the list result
        "summary": "Here are some English words and their French translations:\n\n`translated`\n\nWhich translation do you find most elegant and why?",
    },
    output=["summary"],
)

if __name__ == "__main__":
    print("Graph structure:")
    print(graph.information())
    print("\n" + "=" * 60 + "\n")
    
    # Run with a list of words to translate
    items = ["hello", "world", "spring", "computer", "language"]
    print(f"Input items: {items}\n")
    
    result = graph({"items": items})
    print("Result:")
    print(result)
