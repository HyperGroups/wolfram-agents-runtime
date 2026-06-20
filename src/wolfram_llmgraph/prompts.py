"""Prompt specifications — external counterparts to Wolfram's ``LLMFunction``
prompt forms (LLMGraph reference page, "Possible 'LLMFunction' specifications").

Wolfram accepts as a prompt: a string, a list of strings, ``LLMPrompt["name"]``
(a Wolfram Prompt Repository prompt), ``StringTemplate[...]``, ``TemplateObject[...]``,
or an ``LLMFunction``. We can't reach Wolfram's cloud repository, but we mirror
the *mechanism* with local objects:

* a plain string              -> a template (backtick ``\\`Slot\\``s become deps)
* a list of strings           -> joined with the prompt delimiter, then templated
* ``LLMPrompt("name")``       -> resolved from a :class:`PromptLibrary` (our "repo")
* ``TemplateObject([...])``   -> literal parts + ``Slot("x")`` references, combined

Every form normalizes to a single template string whose ``\\`Slot\\`` references
drive dependency inference, exactly like a plain prompt node.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Wolfram's default PromptDelimiter used to join a list of prompt strings.
PROMPT_DELIMITER = "\n\n"


@dataclass(frozen=True)
class Slot:
    """A template slot — renders to ``\\`name\\``, i.e. a node/input dependency."""

    name: str

    def render(self) -> str:
        return f"`{self.name}`"


@dataclass(frozen=True)
class TemplateObject:
    """A template built from ordered parts (literal strings and :class:`Slot`s).

    Counterpart to Wolfram ``TemplateObject[{...}]``: parts are combined (joined
    by ``joiner``) into a single template string.
    """

    parts: tuple
    joiner: str = ""

    def to_template(self) -> str:
        return self.joiner.join(
            p.render() if isinstance(p, Slot) else str(p) for p in self.parts
        )


@dataclass(frozen=True)
class LLMPrompt:
    """A reference to a named prompt in a :class:`PromptLibrary`.

    Counterpart to Wolfram ``LLMPrompt["name"]`` (Prompt Repository). ``params``
    are optional fixed slot fills applied at resolution time.
    """

    name: str
    params: tuple = ()  # ((slot, value), ...)


#: A small built-in library standing in for the Wolfram Prompt Repository.
#: Register your own with ``PromptLibrary``/``register`` — that is the real point.
BUILTIN_PROMPTS = {
    "Summarize": "Summarize the following:\n\n`Input`",
    "Translate": "Translate the following into `Language`:\n\n`Input`",
    "Explain": "Explain the following clearly and concisely:\n\n`Input`",
    "Critique": "List any errors or issues in the following:\n\n`Input`",
}


class PromptLibrary:
    """A registry of named prompt templates — our local Prompt Repository."""

    def __init__(self, prompts: dict | None = None) -> None:
        self._prompts = dict(BUILTIN_PROMPTS)
        if prompts:
            self._prompts.update(prompts)

    def register(self, name: str, template: str) -> None:
        self._prompts[name] = template

    def resolve(self, name: str) -> str:
        if name not in self._prompts:
            raise KeyError(
                f"LLMPrompt {name!r} is not in the library. "
                f"Known: {sorted(self._prompts)}"
            )
        return self._prompts[name]

    def names(self) -> list[str]:
        return sorted(self._prompts)


_DEFAULT_LIBRARY = PromptLibrary()


def default_library() -> PromptLibrary:
    return _DEFAULT_LIBRARY


def _from_json(value: Any) -> Any:
    """Recognize JSON-expressible prompt specs into prompt objects.

    ``{"llm_prompt": "name", "params": {...}}`` -> LLMPrompt
    ``{"template_object": [parts]}``            -> TemplateObject, where a part
        ``{"slot": "x"}`` becomes Slot("x") and a string stays literal.
    Otherwise the value is returned unchanged.
    """
    if isinstance(value, dict):
        if "llm_prompt" in value:
            params = tuple((value.get("params") or {}).items())
            return LLMPrompt(value["llm_prompt"], params)
        if "template_object" in value:
            parts = tuple(
                Slot(p["slot"]) if isinstance(p, dict) and "slot" in p else p
                for p in value["template_object"]
            )
            return TemplateObject(parts, value.get("joiner", ""))
    return value


def normalize_prompt(value: Any, library: PromptLibrary | None = None) -> str:
    """Normalize any supported prompt spec to a single template string."""
    lib = library or _DEFAULT_LIBRARY
    value = _from_json(value)

    if isinstance(value, str):
        return value
    if isinstance(value, LLMPrompt):
        tmpl = lib.resolve(value.name)
        for k, v in value.params or ():
            tmpl = tmpl.replace(f"`{k}`", str(v))
        return tmpl
    if isinstance(value, TemplateObject):
        return value.to_template()
    if isinstance(value, (list, tuple)):
        return PROMPT_DELIMITER.join(normalize_prompt(v, lib) for v in value)
    raise TypeError(f"unsupported prompt spec: {type(value).__name__}")


def is_prompt_spec(value: Any) -> bool:
    """True if ``value`` is a non-string prompt spec we should normalize."""
    if isinstance(value, (LLMPrompt, TemplateObject)):
        return True
    if isinstance(value, (list, tuple)):
        return True
    if isinstance(value, dict) and ("llm_prompt" in value or "template_object" in value):
        return True
    return False
