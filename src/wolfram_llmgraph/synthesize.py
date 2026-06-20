"""``LLMSynthesize`` — single LLM generation from a prompt (no graph).

Counterpart to Wolfram ``LLMSynthesize`` (its own function / reference page in the
LLM family): one prompt in, generated text out. A thin wrapper over the backend
layer, so it shares the same providers and ``auto`` detection as ``LLMGraph``.
Kept in its own module — the family is a set of independent functions, not one file.

    LLMSynthesize("what has atomic number 2?")            # -> "Helium"
    LLMSynthesize(["You are terse.", "what is `2+2`?"])    # list -> joined prompt
"""

from __future__ import annotations

import asyncio
from typing import Any

from .prompts import normalize_prompt


async def _asynthesize(prompt_str: str, backend: str, model: str | None,
                       config: dict, llm_factory) -> str:
    if llm_factory is not None:
        llm = llm_factory(model)
    else:
        from .backends import make_llm

        llm = make_llm(backend, model, config=config)
    resp = await llm.ainvoke(prompt_str)
    return getattr(resp, "content", resp)


def LLMSynthesize(prompt: Any, *, backend: str | None = None, model: str | None = None,
                  llm_factory=None, **config) -> str:
    """Generate text for ``prompt`` with a single LLM call.

    ``prompt`` may be a string, a list of strings, an ``LLMPrompt`` or a
    ``TemplateObject`` (normalized like an ``LLMGraph`` prompt node). ``backend``
    defaults to ``auto`` detection; ``**config`` accepts ``temperature`` /
    ``max_tokens`` / ``stop`` / ``top_p`` (an inline ``LLMConfiguration``).
    """
    from .backends import resolve_backend

    b = resolve_backend(backend)  # None/"auto" -> detect
    prompt_str = prompt if isinstance(prompt, str) else normalize_prompt(prompt)
    cfg = {k: v for k, v in config.items()
           if k in ("temperature", "max_tokens", "stop", "top_p")}
    return asyncio.run(_asynthesize(prompt_str, b, model, cfg, llm_factory))
