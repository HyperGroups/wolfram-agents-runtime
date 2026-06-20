# 部署与使用教程（Tutorial）

> 从零到跑通的完整路径。命令同时给 **Windows（PowerShell，不依赖 bash）** 和
> **Linux/macOS**。现状能力见 [`STATUS.md`](STATUS.md),家族 CLI 设计见
> [`design/08-agents-cli.md`](design/08-agents-cli.md)。

本教程目标:**安装 → 配置后端 → 跑第一个命令 → 让任务落盘成可在 Mathematica 打开的 LLMGraph
→ 实时监控 → 作为库/在 CI 部署 → 故障排查**。全程**不需要 Wolfram 授权、不需要 Anthropic key**
(用 `claude-cli` 或 Qwen/DeepSeek 任一即可)。

---

## 0. 前置条件

- **Python ≥ 3.10**(推荐 3.12)。验证:`python --version`。
- 推荐安装 [`uv`](https://docs.astral.sh/uv/)(原生二进制,跨平台,无需 bash)。没有也行,用
  `python -m venv` + `pip`。
- **后端三选一**(任一即可,后面第 2 步配):
  - Claude Code CLI 已登录(`claude /login`)—— **零 API key**;
  - Qwen/通义千问 key(`DASHSCOPE_API_KEY`);
  - DeepSeek / OpenAI / Anthropic key。
- **可选**:WolframEngine(仅 `{"wolfram": …}` 计算节点、双引擎 parity、以及把生成的 `.wls`
  在真内核里跑时才需要)。

---

## 1. 安装

### 方式 A:一键脚本(推荐)

```powershell
# Windows（原生 PowerShell，不依赖 bash）
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

```bash
# Linux/macOS
bash scripts/setup.sh
```

脚本会:建虚拟环境 → 安装(可编辑模式)→ 跑 `doctor`。离线也能容错完成大部分步骤。

### 方式 B:手动(uv,各 OS 命令一致)

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"
```

### 方式 C:不装 uv,用标准库 venv

```powershell
# Windows
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

```bash
# Linux/macOS
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

### 激活虚拟环境(让 `wolfram_agents` / `llmgraph` 上 PATH)

```powershell
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
```

```bash
# Linux/macOS
source .venv/bin/activate
```

> **不想激活?** 直接调:`.venv\Scripts\wolfram_agents`(Windows)/ `.venv/bin/wolfram_agents`
> (Unix);或 `python -m wolfram_agents.cli …` 在哪都能用。安装后注册了两个命令:
> **`wolfram_agents`**(家族主入口)和 **`llmgraph`**(图入口,≡ `wolfram_agents graph`)。

验证安装:

```bash
wolfram_agents doctor      # 人读报告 + READY/NOT-READY 结论
wolfram_agents doctor --json   # 机读(供脚本/agent)
```

---

## 2. 配置后端

`doctor` 会告诉你**哪些后端可用、`auto` 会选谁、缺什么怎么补**。两种方式配:

### 引导式(交互/CI 都行)

```bash
wolfram_agents doctor --fix
```

- 无 `.env` → 从 `.env.example` 复制一份;
- 交互终端:列出 key 类后端,选一个把 key 写进 `.env`;
- 非交互(CI/agent):打印最可执行的下一步(`claude /login` 或设某个 key),退出码反映可用性。

### 手动 `.env`

复制 `.env.example` 为 `.env`(已 gitignore,CLI 自动加载),按需填:

```bash
# 任选其一即可
DASHSCOPE_API_KEY=sk-...        # qwen
DEEPSEEK_API_KEY=sk-...         # deepseek
OPENAI_API_KEY=sk-...           # openai
ANTHROPIC_API_KEY=sk-ant-...    # anthropic
# claude-cli 不需要 key —— 只要本机 `claude` 登录过
```

### 固定默认后端(重要,避免"自动选错")

`auto` 按**凭据**自动选后端。如果你 `.env` 里同时有多个 key,可能选到**网络连不上**的那个
(典型:`DASHSCOPE_API_KEY` 在,但 DashScope 端点在你网络下不通 → 报 `Connection error.`)。
**显式固定**最省心:

```bash
# 在 .env 里加一行(本地默认后端)
LLMGRAPH_BACKEND=claude-cli      # 或 qwen / deepseek / openai / anthropic
```

也可临时覆盖,不改文件:

```powershell
# Windows：一次性
$env:LLMGRAPH_BACKEND="claude-cli"; wolfram_agents do "..."
```

```bash
# 或每条命令显式 --backend
wolfram_agents do "..." --backend claude-cli
```

> 每条 `do` / `synthesize` 开头会打印 `using backend: <名字>` 到 stderr —— 一眼确认走的是谁。

---

## 3. 第一个命令

### 3.1 一句话生成(最短路径,LLMSynthesize)

```bash
wolfram_agents synthesize "what has atomic number 2?"        # → Helium
wolfram_agents synthesize "用一句话介绍 LLMGraph"
```

### 3.2 自然语言任务 → 图 → 结果 + **落盘**(`do`,核心)

```bash
wolfram_agents do "write a two-line tea-shop motto, then translate to French"
```

LLM 把任务**编译成一张 LLMGraph**(decompose → … → combine),运行,出结果。开头会看到:

```
using backend: claude-cli
saved LLMGraph -> graphs\write-a-two-line-tea-shop-motto-then-tra.json  (+ .wls for Mathematica)
```

**默认落盘**(这是框架价值点:一个 `do` 任务是一张可移植的 LLMGraph,不是一次性的 langgraph 临时执行):

- `graphs/<slug>.json` —— 本 runtime 的 IR,可 `graph run/info/serve` 复跑;
- `graphs/<slug>.wls` —— **真正的 Wolfram `LLMGraph` spec**,可在 Mathematica/Notebook 打开、检查、上真内核跑。

控制落盘:

```bash
wolfram_agents do "..." --save-graph my/plan   # 自选路径 → my/plan.{json,wls}
wolfram_agents do "..." --no-save              # 不落盘
wolfram_agents do "..." --show-graph           # 把规划出的图打到 stderr
wolfram_agents do "..." --plan-only            # 只规划不运行(打印 IR)
```

### 3.3 在 Mathematica 里打开生成的图

生成的 `.wls` 形如(与 `examples/wolfram/renga_native.wls` 同构):

```wolfram
spec = <|
  "Motto" -> "Write a punchy, two-line motto for a cozy tea shop. ...",
  "Final" -> "Here is a two-line tea-shop motto:\n\n`Motto`\n\n... 'English:' ... 'French:'."
|>;
graph = LLMGraph[spec];
(* runtime-declared output nodes: Final *)
```

直接在 Mathematica 里 `Get["graphs/....wls"]`,或双击打开。这条往返是**内核级验证过的**:把生成的
`.wls` 喂回 `tools/wlg2json.wls`,真 Wolfram 内核会读成 LLMGraph 并吐回**完全相同的 IR**(连
output sink 都自动推对)。

### 3.4 跑现成的图(LLMGraph 编排)

```bash
wolfram_agents graph run examples/renga.json -i Topic=spring
wolfram_agents graph run examples/renga.json -i Topic=autumn --prop all   # 看每个节点
wolfram_agents graph info examples/renga.json                              # 看结构/依赖/输入
llmgraph run examples/renga.json --input '{"Topic":"spring"}'              # 等价的图入口
```

确定性、**免 key**(走 wolframscript)的快速自检:

```bash
llmgraph run examples/wolfram-docs/doubling.json --input '{"Argument": 21}'   # → 42
```

---

## 4. 实时监控(Web)

```bash
llmgraph serve examples/renga.json --backend claude-cli --open
#  → http://127.0.0.1:8765/ 点 ▶ Run;节点 pending → running → done 亮起
llmgraph serve examples/wolfram-docs/output_nodes.json -i Arg1=1 -i Arg2=2   # 确定性,免 LLM
```

零依赖(stdlib HTTP + SSE + 原生 JS)。两个共享实时状态的标签页:**LLMGraph(语义层)** 与
**LangGraph(运行层,含 `draw_mermaid()`)**。接口:`GET /api/graph` `/api/langgraph` `/api/state`
`/api/events`(SSE)`POST /api/run`。详见 [`design/06-runtime-monitor.md`](design/06-runtime-monitor.md)。

---

## 5. 作为 Python 库

```python
from wolfram_llmgraph import LLMGraph

renga = LLMGraph({
    "haiku":    "generate a haiku about `Topic`.",
    "complete": "add an extra stanza to the hokku `haiku` to make it a renga.",
})
print(renga({"Topic": "spring"}))            # 单输出自动解包
```

把图(或 NL 规划出的 IR)导出成 Wolfram:

```python
from wolfram_llmgraph import save_graph, to_wolfram, plan_graph

ir = plan_graph("summarize pros and cons of X")     # NL → IR
print(to_wolfram(ir))                                # → Wolfram LLMGraph spec 字符串
save_graph(ir, "graphs/myplan")                      # 写 graphs/myplan.json + .wls
```

异步 + 事件(LLMGraphSubmit):

```python
task = renga.submit({"Topic": "spring"}, target="All", handlers={
    "NodeSynthesized": lambda e: print("done:", e["CurrentNode"]),
})
task.wait(); print(task.result())
```

---

## 6. 部署场景

### 6.1 CI / 无头(headless)

- 用环境变量传后端与 key,**不要**把 `.env` 提交进库:
  ```bash
  export LLMGRAPH_BACKEND=deepseek
  export DEEPSEEK_API_KEY=sk-...
  wolfram_agents doctor --json    # 退出码:0=有可用后端,非0=没有 → 可作为 gate
  ```
- 离线测试不需要任何 key/网络(用假 LLM):
  ```bash
  uv run pytest        # 或 .venv\Scripts\python -m pytest
  ```

### 6.2 把生成的图沉淀进库

`do` 默认写到 `graphs/`(已 gitignore)。如果你想**保留**某些规划好的图作为资产,用
`--save-graph examples/myflow` 写到非忽略目录,再提交那对 `.json`/`.wls`。

### 6.3 监控服务对外

`llmgraph serve --host 0.0.0.0 --port 8765`。注意它是单文件 stdlib 服务,面向**本地/内网调试**;
对外暴露请自行加反向代理与鉴权。

### 6.4 可切换执行引擎(LangGraph 可拆)

同一份语义可在零依赖 `ReferenceExecutor` 或 `LangGraphExecutor` 上跑:

```bash
LLMGRAPH_EXECUTOR=reference  llmgraph run examples/renga.json -i Topic=spring   # 不碰 LangGraph
```

详见 [`design/09-executor-port.md`](design/09-executor-port.md)。

---

## 7. 故障排查

| 症状 | 原因 | 解决 |
|---|---|---|
| `error: Connection error.` | `auto` 选到网络连不上的后端(常见:DashScope/qwen 端点不通) | 看开头 `using backend:` 是谁;在 `.env` 设 `LLMGRAPH_BACKEND=claude-cli`,或 `--backend claude-cli`;qwen 可改国际站 `QWEN_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1` |
| `wolfram_agents: command not found` | venv 没激活 | `.venv\Scripts\Activate.ps1`(Win)/ `source .venv/bin/activate`(Unix);或直接 `.venv\Scripts\wolfram_agents` |
| `uv venv` 报"拒绝访问 / access denied" | 旧 `.venv` 正被占用(已有进程/编辑器) | 关掉占用进程重试;已有可用 `.venv` 可直接用,不必重建 |
| `RuntimeWarning` 关于 `python -m wolfram_agents.cli` | (已修)早期包加载问题 | 升级到当前版本即可 |
| 中文/输出乱码 | 控制台用了 legacy 代码页 | CLI 已自动把 stdout/stderr 切到 UTF-8;若仍乱码,`chcp 65001` |
| `wolframscript not found`(仅 wolfram 节点/parity 需要) | 没装 WolframEngine 或不在 PATH | 装 WolframEngine,或设 `WOLFRAMSCRIPT_PATH`;纯 LLM/Python 图无需它 |
| `do` 报 `planner failed after N attempts` | LLM 没产出合法/安全/可运行的图 | 加 `--retries 3`;换更强模型 `--model …`;或换后端 |

随时跑 `wolfram_agents doctor` 看完整环境结论。

---

## 速查表

```bash
wolfram_agents doctor [--fix] [--json]       # 环境自检 / 引导安装
wolfram_agents synthesize "<prompt>"         # 一句话生成
wolfram_agents do "<任务>" [--save-graph B] [--no-save] [--show-graph] [--plan-only]
wolfram_agents graph run|info|serve <file>   # 图编排(≡ llmgraph …)
wolfram_agents prompt list|show <name>       # 提示库
wolfram_agents backends [--json]             # 后端 + 凭据状态
```

更多:[`../README.md`](../README.md)(英文总览)· [`STATUS.md`](STATUS.md)(权威现状)·
[`design/`](design/)(架构设计)。
