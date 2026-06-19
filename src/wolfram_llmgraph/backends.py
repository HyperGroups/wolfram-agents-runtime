"""LLM backends for the runtime.

Two ways to reach Claude:

* ``"anthropic"`` (default) — ``langchain-anthropic`` -> ``api.anthropic.com``.
  Needs an API key (``ANTHROPIC_API_KEY``). Per-call billing.

* ``"claude-cli"`` — shells out to the locally installed, **already
  account-logged-in** ``claude`` CLI in headless mode (``claude -p``). This
  reuses your Claude Code subscription login legitimately instead of feeding
  its OAuth token into a third-party API client. The prompt is sent on stdin
  (no command-line length or quoting limits).

Both expose the minimal interface the engine needs: ``await llm.ainvoke(prompt)``
returning an object with a ``.content`` string.
"""

from __future__ import annotations

import asyncio
import shutil


class _Resp:
    __slots__ = ("content",)

    def __init__(self, content: str) -> None:
        self.content = content


class ClaudeCLI:
    """Adapter over the headless ``claude`` CLI (uses the account login)."""

    def __init__(
        self,
        model: str | None = None,
        *,
        timeout: float = 300.0,
        extra_args: list[str] | None = None,
        executable: str | None = None,
    ) -> None:
        self.model = model
        self.timeout = timeout
        self.extra_args = extra_args or []
        self.executable = executable or shutil.which("claude") or "claude"

    async def ainvoke(self, prompt: str) -> _Resp:
        args = [self.executable, "-p", "--output-format", "text"]
        if self.model:
            args += ["--model", self.model]
        args += self.extra_args

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(prompt.encode("utf-8")), self.timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(
                f"claude CLI timed out after {self.timeout}s"
            ) from None

        if proc.returncode != 0:
            detail = err.decode("utf-8", "replace").strip()[:500]
            raise RuntimeError(
                f"claude CLI failed (exit {proc.returncode}): {detail}"
            )
        return _Resp(out.decode("utf-8", "replace").strip())

    async def astream(self, prompt: str):
        """Stream response tokens as they arrive. Yields (chunk, is_final) tuples."""
        args = [self.executable, "-p", "--output-format", "text"]
        if self.model:
            args += ["--model", self.model]
        args += self.extra_args

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        proc.stdin.write(prompt.encode("utf-8"))
        proc.stdin.close()
        
        full_output = []
        try:
            while True:
                line = await asyncio.wait_for(proc.stdout.readline(), self.timeout)
                if not line:
                    break
                decoded = line.decode("utf-8", "replace")
                full_output.append(decoded)
                yield decoded, False
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(
                f"claude CLI timed out after {self.timeout}s"
            ) from None
        
        await proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(
                f"claude CLI failed (exit {proc.returncode})"
            )
        
        yield "".join(full_output), True


#: OpenAI-compatible providers, keyed by backend name. Each entry:
#:   base_url     - the OpenAI-compatible endpoint
#:   env          - env vars searched (in order) for the API key
#:   model        - default model when none is given
#:   base_url_env - optional env var to override base_url
#: Qwen (通义千问) via DashScope: `qwen` = pay-as-you-go, `qwen-tokenplan` =
#: prepaid token-plan account (same endpoint, different key). DeepSeek via its
#: own OpenAI-compatible API.
OPENAI_COMPAT = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "env": ("OPENAI_API_KEY",),
        "model": "gpt-4o",
        "base_url_env": "OPENAI_BASE_URL",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "env": ("DASHSCOPE_API_KEY", "QWEN_API_KEY"),
        "model": "qwen-plus",
        "base_url_env": "QWEN_BASE_URL",
    },
    "qwen-tokenplan": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "env": ("DASHSCOPE_TOKENPLAN_API_KEY", "QWEN_TOKENPLAN_API_KEY"),
        "model": "qwen-plus",
        "base_url_env": "QWEN_BASE_URL",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "env": ("DEEPSEEK_API_KEY",),
        "model": "deepseek-chat",
        "base_url_env": "DEEPSEEK_BASE_URL",
    },
}

#: Each backend's default model, used when no model is given on the graph/node.
BACKEND_DEFAULT_MODEL = {
    "anthropic": "claude-opus-4-8",
    "claude-cli": None,  # let the account's default model apply
    **{name: cfg["model"] for name, cfg in OPENAI_COMPAT.items()},
}

#: Known backends, for help/validation.
BACKENDS = ("anthropic", "claude-cli", *OPENAI_COMPAT)

#: Pricing per 1M tokens (USD). Keys are model name prefixes (longest match first).
#: Format: (input_price, output_price) per 1M tokens.
#: Sources: Anthropic, OpenAI, DashScope, DeepSeek pricing pages (2026-06).
MODEL_PRICING = {
    # Anthropic Claude
    "claude-opus-4": (15.0, 75.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-3-7-sonnet": (3.0, 15.0),
    "claude-3-5-sonnet": (3.0, 15.0),
    "claude-3-haiku": (0.25, 1.25),
    # OpenAI
    "gpt-4o": (2.5, 10.0),
    "gpt-4-turbo": (10.0, 30.0),
    "gpt-4": (30.0, 60.0),
    "gpt-3.5-turbo": (0.5, 1.5),
    # Qwen (DashScope) - CNY per 1M tokens, converted to USD at ~7.2:1
    "qwen-plus": (0.8 / 7.2, 2.0 / 7.2),
    "qwen-turbo": (0.3 / 7.2, 0.6 / 7.2),
    "qwen-max": (2.0 / 7.2, 6.0 / 7.2),
    # DeepSeek
    "deepseek-chat": (0.27, 1.1),
    "deepseek-coder": (0.27, 1.1),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Estimate cost in USD for a given model and token usage.
    
    Returns None if pricing is unknown for the model.
    """
    for prefix, (in_price, out_price) in MODEL_PRICING.items():
        if model.startswith(prefix):
            return (input_tokens * in_price + output_tokens * out_price) / 1_000_000
    return None


def detect_available_backend() -> str | None:
    """Auto-detect which backend has valid credentials configured.
    
    Priority: API keys first (anthropic → openai-compatible), then CLI tools.
    Returns the first backend name whose API key is set, or None if none found.
    """
    import os
    import shutil
    
    # Prefer API keys over CLI tools
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    
    for name, cfg in OPENAI_COMPAT.items():
        if any(os.environ.get(key) for key in cfg["env"]):
            return name
    
    # Fall back to CLI tools
    if shutil.which("claude"):
        return "claude-cli"
    
    return None


def validate_backend(backend: str) -> bool:
    """Check if a backend has valid credentials configured."""
    import os
    import shutil
    
    if backend == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    
    if backend == "claude-cli":
        return shutil.which("claude") is not None
    
    if backend in OPENAI_COMPAT:
        cfg = OPENAI_COMPAT[backend]
        return any(os.environ.get(key) for key in cfg["env"])
    
    return False


def resolve_backend(backend: str | None, strict: bool = False) -> str:
    """Resolve which backend to use.
    
    Args:
        backend: Requested backend name, "auto", or None
        strict: If True, use exactly what's specified (no auto-fallback).
                If False, validate and auto-replace if credentials are missing.
    
    Returns:
        The resolved backend name to use.
    
    Raises:
        ValueError: If strict=True and the specified backend has no credentials.
    """
    if backend is None or backend == "auto":
        detected = detect_available_backend()
        if detected is None:
            if strict:
                raise ValueError("No backend credentials found in environment")
            return "anthropic"
        return detected
    
    if strict:
        if not validate_backend(backend):
            raise ValueError(
                f"Backend {backend!r} has no valid credentials. "
                f"Set the required API key or use auto mode."
            )
        return backend
    
    if not validate_backend(backend):
        detected = detect_available_backend()
        if detected:
            import sys
            print(
                f"warning: backend {backend!r} has no credentials, "
                f"auto-switching to {detected!r}",
                file=sys.stderr,
            )
            return detected
        return backend
    
    return backend


def make_llm(backend: str, model: str | None):
    """Build a backend LLM object for ``backend`` and ``model``.

    ``model=None`` falls back to that backend's default (``BACKEND_DEFAULT_MODEL``).
    """
    import os

    m = model or BACKEND_DEFAULT_MODEL.get(backend)

    if backend == "claude-cli":
        return ClaudeCLI(m)

    if backend == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=m, max_tokens=4096)

    if backend in OPENAI_COMPAT:
        from langchain_openai import ChatOpenAI

        cfg = OPENAI_COMPAT[backend]
        key = next((os.environ[n] for n in cfg["env"] if os.environ.get(n)), None)
        if not key:
            raise RuntimeError(
                f"{backend} backend needs one of {cfg['env']} in the environment"
            )
        base_url = os.environ.get(cfg.get("base_url_env", ""), cfg["base_url"])
        return ChatOpenAI(model=m, api_key=key, base_url=base_url, max_tokens=4096)

    raise ValueError(f"Unknown backend: {backend!r} (use one of {BACKENDS})")
