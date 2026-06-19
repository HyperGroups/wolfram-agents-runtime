# wolfram-llmgraph

A **Wolfram-`LLMGraph`-style runtime built on [LangGraph](https://langchain-ai.github.io/langgraph/)**, with a CLI.

Wolfram Language has `LLMGraph`: you describe a graph as an association of named
nodes, each node's function runs on its *parent* nodes' outputs, dependencies are
inferred automatically, and independent LLM calls are scheduled concurrently.
This project reproduces that programming model in Python, compiling each graph
onto a LangGraph `StateGraph` and running it against Anthropic's Claude models.

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

## The model

* A graph is a dict `{ "name": spec, ... }`.
* A node evaluates on the outputs of its **parent** nodes.
* **Dependencies are inferred automatically:**
  * In a prompt string, every `` `Slot` `` names a parent node — or, if no node
    has that name, an **input argument** supplied at evaluation time.
  * For a Python callable, the **parameter names** are the parents.
* A node runs **as soon as all its dependencies are ready**; independent nodes
  run **concurrently** (LangGraph schedules the supersteps).
* `graph(input)` runs it. `input` is a dict of input arguments. Supplying a value
  for an intermediate node **overrides** (bypasses) that node's evaluation.
* `graph(input, prop)` selects what to return:
  * `None` / `"Automatic"` → output nodes (a single output is unwrapped),
  * `"All"` → every node's result,
  * `"Graph"` → the static graph structure,
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

Two ways to reach Claude — pick per graph (`backend=...` / `"backend"` in JSON /
`--backend` on the CLI):

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

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"
export ANTHROPIC_API_KEY=sk-ant-...   # required to call Claude
```

Default model: `claude-opus-4-8` (via `langchain-anthropic`).

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
