#!/usr/bin/env bash
# One-shot, idempotent setup for wolfram-llmgraph.
#   - creates the .venv (Python 3.12) if missing
#   - installs the package (editable) + dev extras  (tolerant of offline if
#     the deps are already present)
#   - runs `llmgraph doctor` to report what's configured
#
# Agent-friendly: re-running is safe; `doctor`'s exit code (0 = a backend is
# usable, non-zero = none) and `--json` output let an agent finish setup itself.
#
# Usage:  bash scripts/setup.sh
set -uo pipefail
cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
  echo "error: 'uv' not found. Install it (https://docs.astral.sh/uv/) or: pip install uv" >&2
  exit 1
fi

if [ ! -d .venv ]; then
  uv venv --python 3.12 || { echo "error: failed to create .venv" >&2; exit 1; }
fi

# locate the venv python (Windows: Scripts, POSIX: bin)
if [ -x .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python.exe; else PY=.venv/bin/python; fi

# install — best effort; if it fails (e.g. offline) but the deps are already
# importable, keep going so `doctor` can still run.
if ! uv pip install -e ".[dev]"; then
  if "$PY" -c "import wolfram_llmgraph, langgraph" 2>/dev/null; then
    echo "warning: 'uv pip install' failed (offline?), but the package is already installed — continuing." >&2
  else
    echo "error: dependencies are not installed and the install failed (offline?). Connect to a network and retry." >&2
    exit 1
  fi
fi

echo
if "$PY" -m wolfram_llmgraph.cli doctor; then
  echo
  echo "Setup complete. Try:  $PY -m wolfram_llmgraph.cli run examples/renga.json -i Topic=spring"
else
  echo
  echo "Installed OK, but no LLM backend is ready yet (see the hints above)."
  echo "Quickest options:"
  echo "  - 'claude /login'  (Claude Code CLI backend — no API key), or"
  echo "  - set DASHSCOPE_API_KEY=...  (Qwen / 通义千问)"
  echo "then re-check:  $PY -m wolfram_llmgraph.cli doctor"
fi
