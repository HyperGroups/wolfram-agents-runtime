"""Python API demo: LLM nodes + a code node in one graph.

Run with a real key:
    export ANTHROPIC_API_KEY=sk-ant-...
    python examples/python_api.py
"""

from wolfram_llmgraph import LLMGraph


def word_count(haiku: str) -> int:
    """A plain Wolfram-kernel-analog code node: parents come from param names."""
    return len(haiku.split())


graph = LLMGraph(
    {
        "haiku": "generate a haiku about `Topic`.",
        # code node — depends on the 'haiku' node via its parameter name
        "word_count": word_count,
        # LLM node fanning in two parents; runs only after both complete
        "report": "The haiku is:\n`haiku`\n\nIt has `word_count` words. "
        "Write one sentence commenting on its brevity.",
    },
    output=["report"],
)

if __name__ == "__main__":
    print(graph.information())
    print("---")
    print(graph({"Topic": "spring"}))
