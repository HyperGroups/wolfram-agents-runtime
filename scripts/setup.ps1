# One-shot, idempotent setup for wolfram-agents-runtime (Windows / PowerShell).
#   - creates the .venv (Python 3.12) if missing
#   - installs the package (editable) + dev extras (tolerant of offline if already present)
#   - runs `doctor` to report what's configured
#
# Usage (from any prompt):
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
# (the native `uv` commands below also work on their own in PowerShell or cmd.)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "error: 'uv' not found. Install it (https://docs.astral.sh/uv/) or: pip install uv" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path ".venv")) {
    & uv venv --python 3.12
    if ($LASTEXITCODE -ne 0) { Write-Host "error: failed to create .venv" -ForegroundColor Red; exit 1 }
}

$py = ".venv\Scripts\python.exe"

# install — best effort; if it fails (offline) but the deps are already importable, keep going
& uv pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) {
    & $py -c "import importlib.util as u, sys; sys.exit(0 if u.find_spec('wolfram_llmgraph') and u.find_spec('langgraph') else 1)"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "error: dependencies not installed and install failed (offline?). Connect to a network and retry." -ForegroundColor Red
        exit 1
    }
    Write-Host "warning: 'uv pip install' failed (offline?), but the package is already installed - continuing." -ForegroundColor Yellow
}

Write-Host ""
& $py -m wolfram_llmgraph.cli doctor
if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Setup complete. Try:  $py -m wolfram_agents.cli do `"write a two-line tea-shop motto, then translate to French`""
} else {
    Write-Host ""
    Write-Host "Installed OK, but no LLM backend is ready yet (see the hints above)."
    Write-Host "Quickest: 'claude /login' (Claude Code CLI, no key), or set `$env:DASHSCOPE_API_KEY (Qwen),"
    Write-Host "then re-check:  $py -m wolfram_llmgraph.cli doctor"
}
