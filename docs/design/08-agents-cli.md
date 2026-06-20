# `wolfram_agents` —— 从 agents 出发的 CLI 主入口

> 状态:已实现 MVP。最后更新:2026-06-20。
> 参照 `LLMFunctions.pdf`(Wolfram「LLM-Related Functionality」家族指南页)。

## 定位转变:不止 LLMGraph

`LLMGraph` 是"**从图出发**"的一支。但本项目叫 **`wolfram-agents-runtime`** —— 它的身份是
**agents 运行时**,LLMGraph 只是其中一个能力。Wolfram 的家族指南页(`LLMFunctions.pdf`)
本就把 LLM 能力组织成**一组各自独立的函数**:

| 家族分组(LLMFunctions.pdf) | 成员 |
|---|---|
| Programmatic Access | `LLMFunction` · **`LLMGraph` / `LLMGraphSubmit`** · LLMResourceFunction |
| Raw Content Generation | **`LLMSynthesize`** · LLMSynthesizeSubmit |
| Prompt Construction | **`LLMPrompt`** · LLMPromptGenerator |
| Symbolic Chat | ChatObject · ChatEvaluate · ChatSubmit |
| Calling WL from LLMs | LLMTool · LLMToolRequest · LLMToolResponse |
| LLM Specification | $LLMEvaluator · LLMEvaluator · **LLMConfiguration** |

所以主入口应**从 agents/家族出发**,把 LLMGraph 收为其中一个子命令组。

## `wolfram_agents` 命令树(家族 → CLI)

```
wolfram_agents do "<任务>"                NL 任务 → LLM 规划成 LLMGraph → 运行 → 出结果(planner.py)
wolfram_agents synthesize "<prompt>"      LLMSynthesize —— 一次性文本生成(synthesize.py)
wolfram_agents graph run|info|serve …     LLMGraph / LLMGraphSubmit —— 图编排(= llmgraph CLI)
wolfram_agents prompt list|show <name>    LLMPrompt —— 提示库(prompts.py / PromptLibrary)
wolfram_agents backends [--json]          可用 LLM 后端 + 凭据状态
wolfram_agents doctor [--fix] [--json]    环境自检 / 引导式安装(doctor.py)
```

- **`wolfram_agents graph …`** 直接转发给现有 `llmgraph` CLI(单一事实来源,零重复),
  所以 `llmgraph run …` ≡ `wolfram_agents graph run …`,向后兼容。
- 两个 console script 都注册:`wolfram_agents`(家族主入口)、`llmgraph`(图入口)。

### `do` 默认落盘:任务即可移植的 LLMGraph

一个 `do` 任务**是一张 LLMGraph 结构**(工作流),不是一次性的 langgraph 临时执行——这正是框架的
价值点。所以 `do` **默认把规划出的图写到 `graphs/<slug>.{json,wls}`**:

- `.json` —— 本 runtime 的 IR,`graph run/info/serve` 复跑;
- `.wls` —— **真正的 Wolfram `LLMGraph` spec**(`spec=<|name->"prompt with \`Slot\`"|>; LLMGraph[spec]`),
  在 Mathematica 打开/检查/上真内核跑。由 `wolfram_export.py` 生成,是 `tools/wlg2json.wls` 的反向。

planner 出于安全只产 **string-LLM 节点**,恰好是**可无损翻译回 Wolfram 的子集**,所以导出永远忠实
(backtick 槽原样带过,Input/输出 sink 由 LLMGraph 自动推断)。**内核级往返验证**:把生成的 `.wls`
喂回 `wlg2json.wls`,真内核重读得到完全相同的 IR。控制:`--save-graph BASE` / `--no-save`。

## 多包架构(一个系统多个包)

**一个系统可以有多个包**。我们不把所有东西塞进一个包,而是:

```
src/
  wolfram_llmgraph/     ← LLMGraph 库(保留):core/submit/synthesize/prompts/
                          backends/compute/monitor/server/doctor/loaders/cli …
  wolfram_agents/       ← 伞包(系统入口):wolfram_agents CLI + 家族公开 API 门面
    cli.py                `wolfram_agents` 命令(synthesize/graph/prompt/backends/doctor)
    __init__.py           re-export 家族:from wolfram_agents import LLMGraph, LLMSynthesize, …
```

- 依赖方向单一:`wolfram_agents` → `wolfram_llmgraph`(伞包用库,库不反向依赖)。
- 两个 console script:`wolfram_agents = wolfram_agents.cli:main`、`llmgraph = wolfram_llmgraph.cli:main`。
- `wolfram_llmgraph` **原样保留**,既可单独当库用(`from wolfram_llmgraph import LLMGraph`),
  也被 `wolfram_agents` 门面统一暴露(`from wolfram_agents import LLMGraph, LLMSynthesize`)。

## 模块化原则(对照家族的"各自独立")

家族里每个函数 = 一个独立 Wolfram 帮助页 ⇒ 我们也**每个成员一个模块**,不挤在一个文件:

| 模块 | 包 | 家族成员 |
|---|---|---|
| `core.py` | wolfram_llmgraph | `LLMGraph` |
| `submit.py` | wolfram_llmgraph | `LLMGraphSubmit` |
| `synthesize.py` | wolfram_llmgraph | `LLMSynthesize` |
| `prompts.py` | wolfram_llmgraph | `LLMPrompt` / `TemplateObject` / `PromptLibrary` |
| `backends.py` | wolfram_llmgraph | 服务 + `LLMConfiguration` 取值 |
| `doctor.py` | wolfram_llmgraph | 环境自检(无 Wolfram 对应,工程need) |
| `planner.py` | wolfram_llmgraph | NL→图规划(`do` 的实现) |
| `wolfram_export.py` | wolfram_llmgraph | IR→Wolfram `LLMGraph` 导出(`do` 落盘 / Mathematica 往返) |
| `cli.py` + `__init__.py` | **wolfram_agents** | 家族主入口 + 公开 API 门面 |

新成员按同样方式接入:`LLMSynthesizeSubmit`、`LLMTool`(工具调用)、`chat`(ChatObject)
→ 各自一个模块(库内)+ 一个 `wolfram_agents` 子命令(伞包)。需要时也可独立成新包。

## 引导式安装 `wolfram_agents doctor --fix`

`doctor` 暴露安装/凭据状态(见 [`../STATUS.md`](../STATUS.md) 安装节);`--fix` 进一步:

- 若无 `.env` → 从 `.env.example` 复制一份;
- 非交互(CI/agent):打印最可执行的下一步(`claude /login` 或设某个 key),退出码反映可用性;
- 交互(TTY):列出 key-based 后端,选一个并把 key 写入 `.env`(`doctor._set_env_var`)。

agent 可:`wolfram_agents doctor --json` 解析 → 缺什么 → `wolfram_agents doctor --fix` 或写 env → 再 `doctor`。

## 与 `llmgraph` 的关系

`llmgraph` 不废弃,作为"图视角"的专用入口继续存在(也是 `wolfram_agents graph` 的目标)。文档里
"快速上手"既给 `wolfram_agents synthesize "…"`(最短路径:一句话生成),也给 `wolfram_agents graph run …`。

## 参考

- 家族全景 → `LLMFunctions.pdf`(指南页)
- 各成员对照 → [`02-llmgraph-ir.md`](02-llmgraph-ir.md)(LLMGraph)· [`07-llmgraphsubmit.md`](07-llmgraphsubmit.md)(异步)
- 安装/自检 → [`../STATUS.md`](../STATUS.md)
