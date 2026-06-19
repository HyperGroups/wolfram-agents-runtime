"""Wolfram compute nodes for the thin runtime.

A ``{"wolfram": "<WL code>"}`` node runs Wolfram Language code in a real kernel
via a per-call ``wolframscript`` subprocess — the "compute layer". The engine is
woken on demand as a co-processor; for the minute/hour-level tasks this runtime
targets, the few-seconds kernel start is negligible.

The node's dependencies are exposed to the code as an association ``deps``:

    {"wordcount": {"wolfram": "StringLength[deps[\\"haiku\\"]]", "input": ["haiku"]}}

Needs a WolframEngine license + ``wolframscript`` (path via $WOLFRAMSCRIPT_PATH,
else PATH, else the default Windows install location).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile

_DEFAULT_WS = r"C:\Program Files\Wolfram Research\WolframScript\wolframscript.exe"

# Embedded runner: reads {code, inputs} from payload.json, binds `deps`, evaluates
# `code`, writes {ok, result} to out.json (falling back to a string if the result
# is not JSON-exportable).
_RUNNER_WL = r"""
args = Rest[$ScriptCommandLine];
{payloadFile, outFile} = Take[args, 2];
payload = Import[payloadFile, "RawJSON"];
deps = Lookup[payload, "inputs", <||>];
code = payload["code"];
res = Check[ToExpression[code], $Failed];
ok = res =!= $Failed;
If[FailureQ[Quiet[Export[outFile, <|"ok" -> ok, "result" -> res|>, "RawJSON"]]],
  Export[outFile, <|"ok" -> ok, "result" -> ToString[res]|>, "RawJSON"]];
"""


def _resolve_wolframscript() -> str:
    return (
        os.environ.get("WOLFRAMSCRIPT_PATH")
        or shutil.which("wolframscript")
        or _DEFAULT_WS
    )


class WolframCompute:
    """Run WL code in a kernel via a per-call ``wolframscript`` subprocess."""

    def __init__(self, executable: str | None = None, timeout: float = 300.0) -> None:
        self.executable = executable or _resolve_wolframscript()
        self.timeout = timeout

    async def run(self, code: str, inputs: dict):
        payload = {"code": code, "inputs": inputs}
        with tempfile.TemporaryDirectory() as td:
            runner = os.path.join(td, "runner.wls")
            pin = os.path.join(td, "payload.json")
            pout = os.path.join(td, "out.json")
            with open(runner, "w", encoding="utf-8") as fh:
                fh.write(_RUNNER_WL)
            with open(pin, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)

            proc = await asyncio.create_subprocess_exec(
                self.executable, "-file", runner, pin, pout,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, err = await asyncio.wait_for(proc.communicate(), self.timeout)
            except asyncio.TimeoutError:
                proc.kill()
                raise RuntimeError(f"wolframscript timed out after {self.timeout}s") from None

            if not os.path.exists(pout) or os.path.getsize(pout) == 0:
                detail = err.decode("utf-8", "replace").strip()[:500]
                raise RuntimeError(f"wolfram eval produced no output: {detail}")
            with open(pout, encoding="utf-8") as fh:
                data = json.load(fh)

        if not data.get("ok"):
            raise RuntimeError(f"wolfram code failed: {code[:120]!r}")
        return data["result"]
