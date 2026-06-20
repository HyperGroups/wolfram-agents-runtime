"""``wolfram_agents`` — the agents-runtime umbrella for the Wolfram LLM family.

A system can have multiple packages. ``wolfram_llmgraph`` stays as the LLMGraph
**library**; ``wolfram_agents`` is the **umbrella**: it owns the ``agents`` CLI
entry point and re-exports a curated public API composed from the family, so:

    from wolfram_agents import LLMGraph, LLMSynthesize, LLMGraphSubmit, LLMPrompt

New family members slot in here (or in ``wolfram_llmgraph``) as their own modules.
"""

from wolfram_llmgraph import (
    CanceledNode,
    FailedNode,
    LLMGraph,
    LLMGraphSubmit,
    LLMPrompt,
    LLMSynthesize,
    PromptLibrary,
    RunMonitor,
    Slot,
    Task,
    TemplateObject,
    default_library,
    from_dict,
    is_canceled,
    is_failed,
    load_json,
    task_wait,
)

from .cli import main

__all__ = [
    "LLMGraph",
    "LLMGraphSubmit",
    "LLMSynthesize",
    "LLMPrompt",
    "TemplateObject",
    "Slot",
    "PromptLibrary",
    "default_library",
    "RunMonitor",
    "Task",
    "task_wait",
    "CanceledNode",
    "FailedNode",
    "is_canceled",
    "is_failed",
    "from_dict",
    "load_json",
    "main",
]

__version__ = "0.1.0"
