"""Environment self-check — ``llmgraph doctor``.

Makes the install/runtime state **transparent** so a human (or an agent) can see
exactly what's configured and what to do next: which LLM backends have working
credentials, whether the Claude CLI and ``wolframscript`` are available, and which
backend ``--backend auto`` will pick. Reads the same env/.env the runtime uses.

``diagnose()`` returns a structured report (also emitted as JSON by the CLI), so
an agent can parse it and finish setup automatically.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys

from .backends import BACKENDS, OPENAI_COMPAT, detect_available_backend, validate_backend


def _backend_envvars(name: str) -> tuple:
    if name == "anthropic":
        return ("ANTHROPIC_API_KEY",)
    if name == "claude-cli":
        return ()
    if name in OPENAI_COMPAT:
        return tuple(OPENAI_COMPAT[name]["env"])
    return ()


def _backend_hint(name: str) -> str:
    if name == "claude-cli":
        return "install Claude Code CLI and run `claude /login` (no API key needed)"
    envs = _backend_envvars(name)
    if envs:
        return f"set {' or '.join(envs)} (in the environment or .env)"
    return ""


def _wolframscript_path() -> str | None:
    try:
        from .compute import _resolve_wolframscript

        p = _resolve_wolframscript()
        return p if (shutil.which(p) or os.path.exists(p)) else None
    except Exception:
        return None


def _deps_ok() -> bool:
    try:
        import langchain_core  # noqa: F401
        import langgraph  # noqa: F401

        return True
    except Exception:
        return False


def diagnose() -> dict:
    """Return a structured environment report (no side effects)."""
    backends = []
    for name in BACKENDS:
        ok = validate_backend(name)
        envs = _backend_envvars(name)
        if name == "claude-cli":
            detail = "claude CLI on PATH" if ok else "claude CLI not found on PATH"
        else:
            present = [e for e in envs if os.environ.get(e)]
            detail = f"{present[0]} is set" if present else f"missing {', '.join(envs)}"
        backends.append({
            "name": name,
            "available": ok,
            "detail": detail,
            "hint": "" if ok else _backend_hint(name),
        })

    claude = shutil.which("claude")
    ws = _wolframscript_path()
    return {
        "python": platform.python_version(),
        "deps_installed": _deps_ok(),
        "env_file": os.path.exists(".env"),
        "default_backend": detect_available_backend(),  # what `auto` picks
        "usable": any(b["available"] for b in backends),
        "backends": backends,
        "claude_cli": {"available": bool(claude), "path": claude},
        "wolframscript": {"available": bool(ws), "path": ws},
    }


def format_report(rep: dict) -> str:
    """Human-readable report from :func:`diagnose`."""
    ok = lambda b: "OK " if b else "XX "  # noqa: E731
    lines = []
    lines.append("llmgraph doctor — environment check")
    lines.append("=" * 52)
    lines.append(f"  python              {rep['python']}")
    lines.append(f"  [{ok(rep['deps_installed'])}] dependencies installed (langgraph, langchain)")
    lines.append(f"  [{'OK ' if rep['env_file'] else '-- '}] .env file present")
    lines.append("")
    lines.append("LLM backends (need at least one):")
    for b in rep["backends"]:
        line = f"  [{ok(b['available'])}] {b['name']:<14} {b['detail']}"
        lines.append(line)
        if not b["available"] and b["hint"]:
            lines.append(f"          ↳ {b['hint']}")
    lines.append("")
    ws = rep["wolframscript"]
    ws_note = "found" if ws["available"] else "not found — only needed for wolfram-compute nodes"
    lines.append(f"  [{'OK ' if ws['available'] else '-- '}] wolframscript ({ws_note})")
    lines.append("=" * 52)
    if rep["default_backend"]:
        lines.append(f"READY — `--backend auto` will use: {rep['default_backend']}")
    else:
        lines.append("NOT READY — no usable backend. Run `llmgraph doctor --fix`, "
                     "or pick a hint above (`claude /login`, or set DASHSCOPE_API_KEY).")
    return "\n".join(lines)


# -- guided remediation (`--fix`) -----------------------------------------

# backends that are configured by an env var (claude-cli is login-based)
_KEY_BACKENDS = [
    ("qwen", "DASHSCOPE_API_KEY"),
    ("deepseek", "DEEPSEEK_API_KEY"),
    ("openai", "OPENAI_API_KEY"),
    ("anthropic", "ANTHROPIC_API_KEY"),
]


def _set_env_var(name: str, value: str, path: str = ".env") -> None:
    """Set ``NAME=value`` in ``path``, replacing an existing (possibly empty) line."""
    lines = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    out, found = [], False
    for ln in lines:
        if ln.strip().startswith(name + "="):
            out.append(f"{name}={value}")
            found = True
        else:
            out.append(ln)
    if not found:
        out.append(f"{name}={value}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")


def fix(report: dict | None = None, interactive: bool | None = None) -> list[str]:
    """Best-effort guided setup. Returns the list of actions taken / suggested.

    Always safe & non-blocking by default: ensures ``.env`` exists and prints the
    most actionable next step. When attached to a TTY it additionally offers to
    write a key into ``.env`` interactively.
    """
    report = report or diagnose()
    if interactive is None:
        interactive = sys.stdin.isatty()
    actions: list[str] = []

    if not os.path.exists(".env") and os.path.exists(".env.example"):
        shutil.copyfile(".env.example", ".env")
        actions.append("created .env from .env.example")

    if report["usable"]:
        actions.append(f"ready — `--backend auto` will use {report['default_backend']}")
        return actions

    if report["claude_cli"]["available"]:
        actions.append("Claude CLI found — run `claude /login` to use it (no API key)")

    if interactive:
        actions += _interactive_key_entry()
    else:
        actions.append("set one key in .env (e.g. DASHSCOPE_API_KEY=...) "
                       "or run `claude /login`, then re-run `llmgraph doctor`")
    return actions


def _interactive_key_entry() -> list[str]:
    import getpass

    print("\nConfigure a backend (or press Enter to skip):")
    for i, (name, var) in enumerate(_KEY_BACKENDS, 1):
        print(f"  [{i}] {name}  ({var})")
    print("  [Enter] skip — I'll use claude-cli (`claude /login`)")
    choice = input("choice> ").strip()
    if not choice:
        return ["skipped — use `claude /login` for the claude-cli backend"]
    try:
        name, var = _KEY_BACKENDS[int(choice) - 1]
    except (ValueError, IndexError):
        return ["invalid choice — nothing changed"]
    key = getpass.getpass(f"{var}=")
    if not key:
        return ["no key entered — nothing changed"]
    _set_env_var(var, key)
    return [f"wrote {var} to .env — backend {name!r} is now configured"]
