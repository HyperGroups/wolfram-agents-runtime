# wolfram-agents-runtime

A **Wolfram-style LLM/agents runtime on [LangGraph](https://langchain-ai.github.io/langgraph/)**.

Wolfram's *LLM-Related Functionality* is a **family** of functions (`LLMFunction`,
`LLMGraph` / `LLMGraphSubmit`, `LLMSynthesize`, `LLMPrompt`, `LLMConfiguration`,
`LLMTool`, …). This project reproduces that family in Python, with one agent-facing
CLI — **`wolfram_agents`** — and `LLMGraph` as one capability among them, not the whole thing.

```bash
wolfram_agents synthesize "what has atomic number 2?"     # LLMSynthesize — one-shot
wolfram_agents graph run examples/renga.json -i Topic=spring   # LLMGraph — orchestration
wolfram_agents prompt list                                 # LLMPrompt — the prompt library
wolfram_agents doctor --fix                                # environment self-check / setup
```

`wolfram_agents graph …` is the graph entry (also available as `llmgraph …`). The rest of
this README focuses on the **`LLMGraph`** model; see
[`docs/design/08-agents-cli.md`](docs/design/08-agents-cli.md) for the family CLI.

> 🚀 **Just want to get it running?** Jump to the
> [**deployment & usage tutorial**](docs/TUTORIAL.md) — zero to running in a few minutes,
> Windows (no bash) + Unix, with troubleshooting.

---

`LLMGraph`: you describe a graph as an association of named nodes, each node's
function runs on its *parent* nodes' outputs, dependencies are inferred
automatically, and independent LLM calls are scheduled concurrently. This project
reproduces that programming model in Python, compiling each graph onto a LangGraph
`StateGraph` and running it against any of several LLM backends.

```wolfram
(* Wolfram *)
renga = LLMGraph[<|
  "haiku"    -> "generate a haiku about `Topic`.",
  "complete" -> "add an extra stanza to the hokku `haiku` to make it a renga."
|>];
renga[<|"Topic" -> "spring"|>]
```

```python
# This runtime — same model
from wolfram_llmgraph import LLMGraph

renga = LLMGraph({
    "haiku":    "generate a haiku about `Topic`.",
    "complete": "add an extra stanza to the hokku `haiku` to make it a renga.",
})
renga({"Topic": "spring"})
```

## What it does / what it doesn't (yet)

**✅ What this solves today** (all verified, offline tests green):

- **Run Wolfram `LLMGraph`-style graphs with no Wolfram license and no Wolfram
  Cloud** — declarative graph, automatic dependency inference, concurrent
  scheduling, on plain Python/CI.
- **Natural-language task → graph → result**: `wolfram_agents do "<task>"` has an LLM
  plan the task into an `LLMGraph`, then runs it (LLM nodes only, for safety). The
  planned graph is **saved to `graphs/<slug>.json` + `.wls`** — the `.wls` is a real
  Wolfram `LLMGraph` spec you can open and run in Mathematica (kernel-verified
  round-trip), so a `do` task is a portable graph artifact, not throwaway plumbing.
- **Swappable execution engine** (Executor port): the same semantics run on a
  zero-dependency `reference` executor or on LangGraph — proven equal by tests, so
  LangGraph is detachable, not load-bearing.
- **No vendor lock-in, no Anthropic key required.** 6 backends
  (`anthropic`/`openai`/`claude-cli`/`qwen`/`qwen-tokenplan`/`deepseek`),
  per-node mixing, `--backend auto`. Free paths: `claude-cli` (account login) or
  Qwen/DeepSeek.
- **Mix LLM + Python code + real Wolfram-compute + conditional nodes** in one
  graph, with **failure propagation** (`FailedNode`/`CanceledNode`).
- **One-shot generation** (`LLMSynthesize`) and **async + event handlers**
  (`LLMGraphSubmit` → `Task`, NodeSubmitted/Synthesized/Failed…).
- **See inside a pipeline**: live web monitor (SSE), two-layer DAG (LLMGraph
  semantic + compiled LangGraph), per-node status / timing / tokens / cost.
- **Migrate & verify**: Wolfram spec → IR JSON, and **dual-engine parity** vs
  native `LLMGraph` (exact value match on deterministic nodes, local, no key).
- **Agent-friendly setup**: `wolfram_agents doctor [--fix] [--json]` reports exactly
  what's configured and finishes setup — `scripts/setup.sh` (Unix) /
  `scripts/setup.ps1` (Windows).
- **Two switchable CLIs / packages**: `wolfram_agents` (the family) + `llmgraph`
  (graphs); `wolfram_llmgraph` library + `wolfram_agents` umbrella.

**❌ What it does NOT do (yet)** — so you don't get surprised:

- **Not a production agent framework.** No tool-calling (`LLMTool`), no
  loops/state-machines, no checkpoint / resume / memory.
- **Not 100% Wolfram-compute migration.** Heavy symbolic computation stays in
  Wolfram (by design); only `{"wolfram": …}` nodes bridge out, and they need
  `wolframscript`.
- **`LLMConfiguration` tools** and **`Authentication` SystemCredential/ServiceObject**
  are not wired (WL-specific); `Information` returns dicts, not Wolfram
  `Dataset`/`Graph` objects.
- **Streaming** is stable on `claude-cli` only (LangChain-backend streaming pending).
- **`LLMGraphSubmit`** runs the full graph then slices by target (no lazy
  ancestors); one run at a time per graph instance.
- Positioned as a **research / self-hosted runtime + faithful study of Wolfram's
  LLM family**, not a turnkey commercial product.

Full status & the per-feature comparison to Wolfram's docs:
[`docs/STATUS.md`](docs/STATUS.md).

## The model

* A graph is a dict `{ "name": spec, ... }`.
* A node evaluates on the outputs of its **parent** nodes.
* **Dependencies are inferred automatically:**
  * In a prompt string, every `` `Slot` `` names a parent node — or, if no node
    has that name, an **input argument** supplied at evaluation time.
  * For a Python callable, the **parameter names** are the parents.
* A node runs **as soon as all its dependencies are ready**; independent nodes
  run **concurrently** (LangGraph schedules the supersteps).
* `graph(input)` runs it. `input` is a dict of input arguments — or, when the
  graph has a **single** input, a bare value for it (Wolfram's `g[val]`, e.g.
  `graph("winter")`). Supplying a value for an intermediate node **overrides**
  (bypasses) that node's evaluation.
* `graph(input, prop)` selects what to return:
  * `None` / `"Automatic"` → output nodes (a single output is unwrapped),
  * `"All"` → every node's result,
  * `"Graph"` → the static graph structure,
  * `"LLMGraph"` → the structure **annotated with the results** (only nodes whose
    dependencies were satisfied are assigned a result — matches Wolfram's partial form),
  * `"nodeName"` → just that node's result (unwrapped),
  * `["a", "b"]` → an association of only those nodes.

### Node specs

| spec | meaning |
|------|---------|
| `"prompt string"` | LLM node; `` `Slot` `` references become dependencies |
| `python_callable` | code node; parameter names become dependencies |
| `{"prompt": "...", "model": "..."}` | LLM node with a per-node model |
| `{"listable_llm": "...", "input": [...]}` | **ListableLLMFunction** — maps LLM calls over list inputs in parallel; each element is substituted into the template |
| `{"fn": callable, "input": [...]}` | code node with explicit dependencies |
| `{"wolfram": "<WL code>", "input": [...]}` | Wolfram compute node — runs in a kernel via `wolframscript`; deps as `deps["name"]` (needs WolframEngine). On `$Failed`, returns `FailedNode` instead of raising |
| `{..., "test": "<WL or callable>", "test_input": [...]}` | conditional node (`ConditionalNode`) — evaluates only when `test` is truthy, else yields `Missing[CanceledNode, name]` |
| `["text1", "text2 \`Slot\`"]` | a **list of strings** prompt — joined with the prompt delimiter, then templated |
| `{"llm_prompt": "name", "params": {...}}` | **`LLMPrompt["name"]`** — a named prompt resolved from a `PromptLibrary` (our Prompt-Repository counterpart) |
| `{"template_object": ["lit", {"slot": "X"}]}` | **`TemplateObject`** — literal parts + slot references combined into a template |
| `{"prompt": "...", "temperature": .., "max_tokens": .., "stop": [..], "system": ".."}` | per-node **`LLMConfiguration`** (overrides the graph-level `llm_config=` / `LLMEvaluator`) |

### Prompt specs, LLMConfiguration & Authentication

The prompt forms above are external counterparts to Wolfram's `LLMFunction` prompt
specs (string / list / `LLMPrompt` / `TemplateObject` / `StringTemplate`). Build a
prompt library with `PromptLibrary({"Greet": "Say hi to \`Name\`"})` and pass it as
`LLMGraph(..., prompts=lib)`.

`LLMConfiguration` is set graph-wide via `LLMGraph(..., llm_config={"temperature": 0.2,
"max_tokens": 512})` (Wolfram's `LLMEvaluator`) and overridden per node. `Authentication`
chooses the key source: `authentication={"api_key": "..."}` or `{"env": "MY_KEY"}`
(default reads the backend's standard env var). `Information` mirrors Wolfram:
`graph.information("Properties" | "Nodes" | "Graph" | "LLMEvaluator")`.

### Async evaluation (`LLMGraphSubmit`)

`graph.submit(...)` (or `LLMGraphSubmit(graph, ...)`) runs the graph asynchronously
and returns a `Task` — the counterpart to Wolfram's `LLMGraphSubmit` / `TaskObject`.
It fires `HandlerFunctions` on events (`NodeSubmitted` / `NodeSynthesized` /
`NodeCanceled` / `NodeFailed` / `ResultGenerated` + the task lifecycle). It lives in
its own module (`submit.py`), built on the same `RunMonitor` event feed as the web
monitor. See [`docs/design/07-llmgraphsubmit.md`](docs/design/07-llmgraphsubmit.md).

```python
task = graph.submit({"Topic": "spring"}, target="All", handlers={
    "NodeSynthesized": lambda e: print("done:", e["CurrentNode"]),
    "TaskFinished":    lambda e: print(e["GraphResults"]),
})
task.wait()          # TaskWait
task.result()        # GraphResults for the target
```

### Failure propagation

When a node fails (Wolfram `$Failed`) or is canceled (`ConditionalNode` test is false), the
failure propagates to downstream nodes:

- `FailedNode(name, reason)` — a node whose evaluation failed
- `CanceledNode(name)` — a conditional node whose test was false

Downstream nodes that depend on a `FailedNode` or `CanceledNode` also receive the same
sentinel, preventing cascading errors. Independent branches are unaffected.

```python
from wolfram_llmgraph import LLMGraph, is_failed, is_canceled

g = LLMGraph({
    "Fail": {"wolfram": "1/0"},
    "Down": {"fn": lambda Fail: f"got {Fail}"},  # also FailedNode
    "OK": {"fn": lambda: 42},  # independent, unaffected
})
result = g({}, "All")
assert is_failed(result["Fail"])
assert is_failed(result["Down"])
assert result["OK"] == 42
```

Outputs default to the **sink** nodes (those nobody depends on). Override with
`output=[...]` (Python) or `"output": [...]` (JSON).

## CLI

```bash
llmgraph run examples/bestpoem.json
llmgraph run examples/renga.json --input '{"Topic": "spring"}'
llmgraph run examples/renga.json -i Topic=autumn --prop all
llmgraph run examples/renga.json -i Topic=autumn --prop haiku
llmgraph run examples/renga.json -i Topic=autumn --prop haiku,complete
llmgraph info examples/renga.json
```

* `--input '<json>'` or `--input @file.json` — input arguments as JSON.
* `-i KEY=VALUE` — set a single argument (repeatable).
* `--prop` — what to return: `auto` (output nodes, default), `all` (every node),
  `Graph` (structure), a node name, or a comma-separated list of node names.
* `--model <id>` — override the graph-wide default model.
* `--backend <name>` — LLM backend: `auto` (default, auto-detect) or specify: `anthropic`, `claude-cli`, `qwen`, `qwen-tokenplan`, `openai`, `deepseek`.
* `--backend-strict` — manual mode: use exactly the specified backend, fail if credentials missing.

## JSON graph format

```json
{
  "nodes": {
    "Poet1": "write a short poem about summer",
    "Poet2": "write a haiku about winter",
    "Judge": "Choose the best:\n1) `Poet1`\n2) `Poet2`"
  },
  "output": ["Judge"],
  "model": "claude-opus-4-8"
}
```

Code (callable) nodes can't be expressed in JSON — use the Python API for those.

## Backends

Six LLM backends — pick per graph (`backend=...` / `"backend"` in JSON /
`--backend` on the CLI), or per node (`{"prompt": "...", "backend": "openai"}`).
`--backend auto` (default) auto-detects from available credentials:

| backend | how it authenticates | needs |
|---------|----------------------|-------|
| `anthropic` | `langchain-anthropic` → `api.anthropic.com` | `ANTHROPIC_API_KEY`, per-call billing |
| `claude-cli` | shells out to your **account-logged-in** local `claude` CLI (`claude -p`, prompt on stdin) | Claude Code installed + logged in (`claude /login`) |
| `qwen` | Qwen / 通义千问 via DashScope OpenAI-compatible endpoint (`langchain-openai`) | `DASHSCOPE_API_KEY` (pay-as-you-go) |
| `qwen-tokenplan` | same as `qwen`, different account/key (prepaid token plan) | `DASHSCOPE_TOKENPLAN_API_KEY` |
| `deepseek` | DeepSeek via its OpenAI-compatible API (`langchain-openai`) | `DEEPSEEK_API_KEY` |
| `openai` | OpenAI API (`langchain-openai`) | `OPENAI_API_KEY` |

### Auto/Manual 模式

默认使用 **auto 模式**,自动检测可用凭据并选择 backend:

```bash
# Auto mode - 自动检测可用 backend
llmgraph run examples/renga.json -i Topic=spring

# Manual mode - 强制使用指定 backend,无凭据则报错
llmgraph run examples/renga.json -i Topic=spring --backend anthropic --backend-strict

# Auto fallback - 指定 anthropic 但无凭据,自动切换到可用的
llmgraph run examples/renga.json -i Topic=spring --backend anthropic
```

**检测优先级**:API keys(`ANTHROPIC_API_KEY` → `DASHSCOPE_API_KEY`/`OPENAI_API_KEY`/...) → CLI tools(`claude`)。

如果指定的 backend 没有凭据,auto 模式会自动切换到可用的 backend 并打印 warning;manual 模式(`--backend-strict`)则直接报错。

Keys are read from the environment (see [`.env.example`](.env.example)) — never hard-coded.
The **same keys** also drive the Wolfram side via the cloud-optional access layer
`Get["examples/wolfram/llm.wls"]` (`ask[...]`) — see [`docs/`](docs/README.md).

```bash
llmgraph run examples/renga.json -i Topic=spring --backend qwen
llmgraph run examples/renga.json -i Topic=spring --backend qwen-tokenplan
LLMGRAPH_BACKEND=qwen llmgraph run examples/renga.json -i Topic=spring
```

The `claude-cli` backend lets you reuse your existing Claude Code subscription
login. It does this the supported way — by driving the `claude` CLI in headless
mode — **not** by extracting the subscription OAuth token and feeding it to a
third-party API client (that violates Anthropic's terms and is brittle).

```bash
# uses your account login, no API key:
llmgraph run examples/bestpoem.json --backend claude-cli
```

```python
LLMGraph({...}, backend="claude-cli")
```

Note: each `claude-cli` LLM node spawns a `claude` subprocess, so this backend is
heavier per call than the API and best for low-concurrency graphs.

## Install

The `uv` commands below are the same on every OS (uv is a native binary — no bash needed):

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"

# activate the venv so `wolfram_agents` / `llmgraph` are on PATH:
#   Linux/macOS  :  source .venv/bin/activate
#   Windows (PS) :  .venv\Scripts\Activate.ps1
wolfram_agents doctor            # check what's configured (backends, tools) — see below
```

**One-shot** (creates the venv, installs, runs `doctor`):

```bash
# Linux/macOS
bash scripts/setup.sh
# Windows (PowerShell) — no bash required
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

> Not activating the venv? Call the tools directly: `.venv\Scripts\wolfram_agents`
> (Windows) or `.venv/bin/wolfram_agents` (Unix). `python -m wolfram_agents.cli …`
> works anywhere.

**New here?** Follow the step-by-step **[deployment & usage tutorial](docs/TUTORIAL.md)**
(install → configure a backend → first command → save a graph & open it in
Mathematica → monitor → CI → troubleshooting).

### Requirements & dependencies

- **Python ≥ 3.10** (`uv` recommended; `python -m venv` + `pip install -e ".[dev]"` also works).
- **Runtime deps** (installed automatically): `langgraph`, `langchain-core`,
  `langchain-anthropic`, `langchain-openai` — the LangGraph engine + LLM clients.
  *(Execution is pluggable — see the Executor port; the zero-dep `reference`
  executor needs none of LangGraph, which is slated to become an optional extra.)*
- **Dev** (`".[dev]"`): `pytest`.
- **Per backend**: only the one credential you actually use (table below) — or
  none, with the `claude-cli` backend.
- **Optional**: a WolframEngine, only for `{"wolfram": …}` compute nodes (below).

Two commands are installed: **`wolfram_agents`** (the family entry) and **`llmgraph`**
(the graph entry, ≡ `wolfram_agents graph`).

**You do not need an Anthropic API key.** The default backend is `auto`, which
picks whatever credentials you actually have. Any **one** of these is enough:

| you have… | backend picked | setup |
|-----------|----------------|-------|
| Claude Code CLI logged in | `claude-cli` | `claude /login` — **no API key** |
| Qwen / 通义千问 key | `qwen` | `export DASHSCOPE_API_KEY=...` |
| DeepSeek / OpenAI / Anthropic key | `deepseek` / `openai` / `anthropic` | set the matching key (see [`.env.example`](.env.example)) |

Keys are read from the environment or a `.env` file (auto-loaded, gitignored).

### WolframEngine (optional — only for `{"wolfram": …}` nodes)

The runtime is **fully usable without any Wolfram software**. A Wolfram kernel is
needed only for:

- **`{"wolfram": "<WL>"}` compute nodes** — deterministic computation inside a graph;
- the **dual-engine parity** tooling (`tools/parity.py`, `parity_sweep.py`) that
  cross-checks against native `LLMGraph`.

To enable it:

1. Install a **WolframEngine** (free for developers) or any Wolfram product that
   ships `wolframscript`.
2. Put `wolframscript` on `PATH`, or point to it explicitly:
   ```bash
   export WOLFRAMSCRIPT_PATH="/path/to/wolframscript"
   # Windows default: C:\Program Files\Wolfram Research\WolframScript\wolframscript.exe
   ```
3. Verify: `llmgraph doctor` shows `[OK ] wolframscript (found)`.

Graphs with **no** `wolfram` nodes (LLM + Python nodes) never touch Wolfram.

### `llmgraph doctor` — verify the environment

Run it anytime to see, transparently, what's set up and what to do next:

```bash
llmgraph doctor          # human-readable report + a READY/NOT-READY verdict
llmgraph doctor --json   # machine-readable (for scripts / agents)
```

It reports each backend's credential status (with a fix hint), whether the Claude
CLI and `wolframscript` are present, and which backend `--backend auto` will use.
Exit code is `0` when at least one backend is usable, non-zero otherwise — so an
agent can run it, parse the JSON, and finish setup on its own.

## Examples

Bundled under [`examples/`](examples/). Quickest first check is the **no-key**
deterministic path (runs locally via `wolframscript`):

| what | command | needs |
|---|---|---|
| deterministic compute | `llmgraph run examples/wolfram-docs/doubling.json --input '{"Argument": 21}'` → `42` | WolframEngine (no key) |
| deterministic DAG | `wolfram_agents graph run examples/wolfram-docs/output_nodes.json -i Arg1=1 -i Arg2=2 --prop all` | WolframEngine (no key) |
| one-shot generation | `wolfram_agents synthesize "name one noble gas, single word only"` → `Argon` | any LLM backend |
| multi-step graph | `wolfram_agents graph run examples/renga.json -i Topic=spring` | any LLM backend |
| parallel map | `llmgraph run examples/wolfram-docs/parallel.json --input '{"words": ["cat","dog"]}'` | any LLM backend |
| **NL task → graph → result** | `wolfram_agents do "write a two-line tea-shop motto, then translate it to French"` | any LLM backend |

`wolfram_agents do` plans your task into an `LLMGraph` with an LLM, then runs it. Add
`--show-graph` to see the generated graph, or `--plan-only` to just print the IR.
It also **writes the graph to `graphs/<slug>.json` + `.wls`** (override with
`--save-graph BASE`, disable with `--no-save`); open the `.wls` in Mathematica to
inspect or run the same `LLMGraph` on a real kernel.
Real run (claude-cli) of the command above produced:

```
--- planned LLMGraph ---            (an LLM wrote this)
{ "nodes": {
    "Motto": "Write a catchy two-line motto for a tea shop. Output ONLY the two lines.",
    "Final": "Here is a motto:\n`Motto`\n\nTranslate it into idiomatic French ..." },
  "output": ["Final"] }
--- result ---
English: Steeped to perfection, sip by sip, / Your daily calm in every cup.
French:  Infusé à la perfection, gorgée après gorgée, / Votre sérénité quotidienne dans chaque tasse.
```

Every official Wolfram `LLMGraph` doc example is ported under
[`examples/wolfram-docs/`](examples/wolfram-docs/), each with its own page.

## Test

```bash
uv run pytest        # offline; uses a fake LLM, no API key or network needed
```

## Live monitor (web app)

Watch a graph execute in real time — a faithful, streamable version of the state
Wolfram surfaces while running an `LLMGraph` (its "Computing nodes / Elapsed time"
progress panel + per-node dependency state + token usage):

```bash
llmgraph serve examples/renga.json --backend claude-cli --open
#  → http://127.0.0.1:8765/ — click ▶ Run; nodes light up pending → running → done
llmgraph serve examples/wolfram-docs/output_nodes.json -i Arg1=1 -i Arg2=2   # deterministic, no LLM
```

The page (zero-dependency: stdlib HTTP + SSE, vanilla JS) shows the DAG with live
status colors, a progress bar + elapsed timer, per-node timing / output preview /
token usage, and a streaming event log. It has **two tabs sharing the live state**:

* **LLMGraph (semantic)** — your declarative graph: nodes, inferred deps, input
  vertices, output badges, kind colors (the `Information[g,"Graph"]` view).
* **LangGraph (runtime)** — the *compiled* `StateGraph` we actually run
  (`__start__ → … → __end__`), plus LangGraph's own `draw_mermaid()` export.

**前端特性**:
- **SVG pan/zoom**:鼠标滚轮缩放、拖拽平移、fit to view
- **SSE 自动重连**:指数退避,网络断开后自动恢复
- **亮暗主题**:一键切换,localStorage 持久化
- **键盘快捷键**:`Ctrl+Enter` 运行、`Esc` 取消选择
- **JSON 实时校验**:输入错误时红色提示
- **历史分页**:大量运行记录时按需加载
- **移动端响应式**:640px 断点自适应
- **流式 token 显示**:LLM 节点生成过程实时显示
- **成本估算**:summary bar 显示 token 用量和预估成本(USD)
- **多运行对比**:选择多个历史运行,侧边对比每个节点的输出、状态、耗时、模型

To wire it into your own UI: `GET /api/graph`, `GET /api/langgraph`,
`GET /api/state`, `GET /api/events` (SSE), `POST /api/run`.

In Python, attach a `RunMonitor` directly:

```python
from wolfram_llmgraph import LLMGraph, RunMonitor
mon = LLMGraph({...}, monitor=RunMonitor()).monitor   # snapshot() / subscribe()
```

See [`docs/design/06-runtime-monitor.md`](docs/design/06-runtime-monitor.md).

## Parity with native Wolfram `LLMGraph`

The official examples from Wolfram's own `LLMGraph` reference page are transcribed
into this runtime's IR under [`examples/wolfram-docs/`](examples/wolfram-docs/) and
run on **both** engines — this runtime and the WolframEngine native `LLMGraph` —
then cross-validated (structure exactly; deterministic Wolfram-code nodes by value):

```bash
python tools/parity_sweep.py             # deterministic tier — exact value parity, fully local, no key
python tools/parity_sweep.py --with-llm  # also the LLM examples (shared backend on both sides)
```

## License

MIT
