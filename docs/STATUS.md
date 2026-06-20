# 当前进展(STATUS)

> 快照日期:2026-06-20。本文件是**现状的权威记录**;前瞻计划见
> [`drafts/roadmap.md`](drafts/roadmap.md)。
> 约定:**「已实测」= 本机内核/测试实跑确认;「未重跑」= 早前验证过、本轮未再跑;
> 「设计」= 仅文档、未落地。** 不把推断当确认。

## 一句话

Wolfram `LLMGraph` 编程模型的**瘦运行时**已可用:声明式图 + 依赖自动推断 + 并发调度。
**语义核与执行器解耦**(Executor 端口):同一份语义可在零依赖 `ReferenceExecutor` 或
`LangGraphExecutor` 上跑、可切换——「超集 = Wolfram 子集 + 可拆外圈」由内部 parity 测试焊死,不再被 LangGraph 绑死。
支持五类节点(LLM / ListableLLM / Python 代码 / Wolfram 计算 / 条件),失败传播,完整属性选择,
提示规格 / `LLMConfiguration` / `Authentication` / `Information` 对照实现,以及异步提交
`LLMGraphSubmit`。6 个 LLM 后端(节点级可混合)+ 自动检测。与 Wolfram 原生 `LLMGraph` 做
**双向 parity 互验**,并配 Web 实时监控 + 两层可视化。NL 任务(`do`)规划出的图**默认落盘为
`.json` + Wolfram `.wls`**——可在 Mathematica 打开、内核级往返验证。**139 个离线测试全过**(免 key、免网络)。

## 能力清单

| 模块 | 文件 | 状态 | 说明 |
|---|---|---|---|
| 核心引擎(语义核) | `core.py` | ✅ 已实测 | 解析 / 依赖推断 / 并发 / 属性选择(含 `"LLMGraph"` 结果标注图 + 部分形)/ 覆盖 / 单输入裸值 / 条件节点 / `information(prop)` 多形态 / **ListableLLMFunction** / **失败传播(`FailedNode`)** / **提示规格对照** / **`LLMConfiguration`(图级+节点级)** / **`Authentication`**;**产出中性 `ExecutionPlan`,零 LangGraph 耦合** |
| **Executor 端口** | `executors.py` | ✅ 已实测 | 语义/执行解耦的可切换执行器:`ReferenceExecutor`(零依赖,拓扑波次+asyncio)/ `LangGraphExecutor`(超集长这边)/ `get_executor`。`executor=`/`$LLMGRAPH_EXECUTOR` 切换。**内部 parity:两 executor 结果精确相等**=「超集=子集+可拆」的测试契约。见 [`design/09-executor-port.md`](design/09-executor-port.md) |
| 提示库 | `prompts.py` | ✅ 已实测 | `LLMPrompt`/`TemplateObject`/`Slot`/`PromptLibrary`——Wolfram 提示规格的外部对照 |
| 异步提交 | `submit.py` | ✅ 已实测 | `LLMGraphSubmit`/`Task`/`task_wait`——对照 `LLMGraphSubmit`:`TaskObject` + `HandlerFunctions` 事件 + `HandlerFunctionsKeys` + `target`,架在 monitor 事件流上。见 [`design/07-llmgraphsubmit.md`](design/07-llmgraphsubmit.md) |
| Wolfram 计算节点 | `compute.py` | ✅ 已实测 | `{"wolfram":"<WL>"}` 经 `wolframscript` 子进程在内核求值;失败时返回 `FailedNode` 而非抛错 |
| LLM 后端 | `backends.py` | ✅ 已实测 | 6 个:`anthropic`/`openai`/`claude-cli`/`qwen`/`qwen-tokenplan`/`deepseek`;**节点级切换**(同图混合 provider)、**自动检测**(`--backend auto`)/`--backend-strict`、成本估算 |
| IR + JSON 加载 | `loaders.py` | ✅ 已实测 | 见 [`design/02-llmgraph-ir.md`](design/02-llmgraph-ir.md) |
| CLI | `cli.py` | ✅ 已实测 | `llmgraph run` / `info` / `serve` / **`doctor`**,`--input/-i/--prop/--model/--backend/--backend-strict`,`.env` 自动加载 |
| **agents 伞包** | `wolfram_agents/`(`cli.py` + `__init__`) | ✅ 已实测 | **独立的系统入口包**(依赖 `wolfram_llmgraph` 库):`wolfram_agents` CLI(**`do`**/`synthesize`/`graph`/`prompt`/`backends`/`doctor`)+ 家族 API 门面。多包架构,`wolfram_llmgraph` 原样保留。见 [`design/08-agents-cli.md`](design/08-agents-cli.md) |
| **NL→图规划** | `planner.py` | ✅ 已实测 | `wolfram_agents do "<任务>"`:LLM 把自然语言任务**编译成 LLMGraph IR**→运行→出结果。**安全**:只收 string-LLM 节点,拒绝 `wolfram`/`fn`/`test`(防 RCE)。**鲁棒**:可加载/输出存在/无环校验 + **自我修复重试**(错误回喂规划器,`--retries`,默认 2)。`plan_graph`/`run_task`/`check_runnable` |
| **IR→Wolfram 导出** | `wolfram_export.py` | ✅ 已实测 | `to_wolfram`/`save_graph`/`slugify`:把 IR 反向序列化成 Wolfram `spec=<\|name->"prompt with \`Slot\`"\|>; LLMGraph[spec]` 脚本(`wlg2json.wls` 的反向)。`do` **默认落盘** `graphs/<slug>.json + .wls`(`--save-graph`/`--no-save`)。planner 只产 string-LLM 节点=无损子集,**内核级往返验证**(真内核重读 `.wls` 得到完全相同 IR + 推对 output sink) |
| LLMSynthesize | `synthesize.py` | ✅ 已实测 | 一次性文本生成(家族成员,独立模块);`wolfram_agents synthesize "…"` / `LLMSynthesize(...)` |
| 环境自检 | `doctor.py` + `scripts/setup.{sh,ps1}` | ✅ 已实测 | `doctor [--json] [--fix]`:逐后端凭据 + 修复提示 + claude/wolframscript 检测 + `auto` 解析,退出码反映可用性;**`--fix`** 建 `.env` + 引导。一键安装:`setup.sh`(Unix)/ **`setup.ps1`(Windows 原生 PowerShell,不依赖 bash)**,离线容错 |
| 运行时监控 | `monitor.py` + `server.py` + `webapp/index.html` | ✅ 已实测 | 节点生命周期事件 + 计时 + token 用量 + 成本;零依赖 HTTP+SSE + 单文件前端。**两层视图**(LLMGraph 语义层 `/api/graph` + LangGraph 运行层 `/api/langgraph` + `draw_mermaid()`);SVG pan/zoom、SSE 自动重连、亮暗主题、流式 token、多运行对比、多 notebook。见 [`design/06-runtime-monitor.md`](design/06-runtime-monitor.md) |
| 双引擎 parity | `tools/parity.py` + `run_native.wls` | ✅ 已实测 | 同一 IR 两引擎各跑:结构精确 + 确定性节点值精确 + LLM 并列;`--timeout` 守护防孤儿内核锁 license |
| 文档示例双向测试 | `tools/parity_sweep.py` + `examples/wolfram-docs/` | ✅ 已实测 | 官方示例移植 + 一键扫描互验 |
| WL→IR 转译器 | `tools/wlg2json.wls` | ✅ 已实测 | Wolfram `LLMGraph` spec → IR(无损子集) |
| Cloud-optional 接入层 | `examples/wolfram/llm.wls` | ✅ 已实测 | 统一 `ask[]`,默认绕开 Wolfram Cloud |

## 节点类型 & 求值支持矩阵

| 项 | Wolfram 形式 | 我们的 IR / API | parity 档 |
|---|---|---|---|
| LLM | `"prompt `Slot`"` / `LLMFunction` / `StringTemplate` | `"prompt"` 或 `{"prompt":..,"model":..,"backend":..,"temperature":..,"system":..}` | 结构(LLM 非确定) |
| ListableLLM | `ListableLLMFunction["… `Slot`"]` | `{"listable_llm":"…","input":[...]}`——并发 map 过列表,输出恒列表 | 结构 |
| 提示规格 | `{"t1","t2"}` / `LLMPrompt["n"]` / `TemplateObject[...]` | 列表 / `{"llm_prompt"}` / `{"template_object"}` | — |
| 代码(Python) | `EvaluationFunction -> (f &)` | `callable` 或 `{"fn":callable,"input":[...]}` | 仅瘦引擎 |
| Wolfram 计算 | `EvaluationFunction -> (WL &)` | `{"wolfram":"<WL>","input":[...]}` | **确定性·精确值** |
| 条件 `ConditionalNode` | `<|EvaluationFunction, TestFunction, InputTestFunction|>` | 任意节点 + `"test"` + `"test_input"` | **确定性·精确值** |
| 属性选择 | `g[in]` / `g[in,All]` / `g[in,"LLMGraph"]` | `g(val|dict, "All"/"name"/[...]/"Graph"/"LLMGraph")` | — |
| 中间覆盖 | `g[<|"Node"->val|>]` | `g({"Node":val})` | — |
| 失败传播 | `$Failed` / 被取消节点下游 | `FailedNode` / `CanceledNode` 自动传播 | — |
| 异步 | `LLMGraphSubmit[...]` → `TaskObject` | `g.submit(...)` / `LLMGraphSubmit(...)` → `Task` + 事件 | — |
| 选项 | `LLMEvaluator`/`Authentication`/`ProgressReporting` | `llm_config=`/`authentication=`/`monitor=` | — |

## 官方文档示例移植(`examples/wolfram-docs/`,每例自带 `.json` + `.md`)

| 示例 | 来源 cell | 档 | 双向测试 |
|---|---|---|---|
| `doubling`(`2*#Argument`) | 15–16 | det | ✅ 已实测:`42 == 42` |
| `output_nodes`(三节点 DAG) | 21–29 | det | ✅ 已实测:三节点值全等 |
| `conditioned`(`ConditionalNode`) | 17–19 | det | ✅ 已实测:真→`"NodeHasRun"`、假→`Missing[CanceledNode,…]` |
| `whatis` / `restyle` / `bestpoem` / `renga` | 8–11/94/2–7 | llm | 结构 parity(早前 PASS,本轮未重跑) |

`parity_sweep.py` 默认只跑 det 档(本机、免 key);`--with-llm` 才跑 llm 档。

## 测试(已实测,`pytest -q` → **139 passed**,免 key/网络)

| 文件 | 数 | 覆盖 |
|---|---|---|
| `test_core.py` | 24 | 依赖推断/并发/覆盖/属性选择/条件节点/ListableLLM/失败传播 |
| `test_loaders.py` | 18 | `from_dict`/`load_json`/各字段 |
| `test_backends.py` | 12 | 成本估算/自动检测/验证 |
| `test_notebook.py` | 11 | notebook 创建/列表/激活/保存/加载 |
| `test_prompts_config.py` | 10 | 提示规格/LLMConfiguration/Authentication/Information |
| `test_wolfram_docs_examples.py` | 7 | 官方示例静态结构 |
| `test_monitor.py` | 6 | 节点状态/事件流/错误/流式/成本 |
| `test_submit.py` | 6 | LLMGraphSubmit 事件/结果/target/取消/失败 |
| `test_executors.py` | 8 | **Executor 端口内部 parity**:Reference vs LangGraph 结果精确相等、override/失败传播/get_executor |
| `test_planner.py` | 13 | **NL→图规划**:JSON抽取/校验(拒wolfram·fn)/环路·输出校验/**自我修复重试**/run_task |
| `test_agents_cli.py` | 6 | `wolfram_agents` 家族 CLI:synthesize/prompt/graph 转发/backends/doctor --fix |
| `test_wolfram_export.py` | 8 | **IR→Wolfram 导出**:`to_wolfram`(spec 形/转义/assoc 节点/拒非 LLM)+ `save_graph`/`slugify` + `do` 默认落盘/`--no-save` |
| `test_inputs.py` / `test_llmgraph_prop.py` / `test_doctor.py` | 3 / 3 / 3 | 裸值单输入 / `"LLMGraph"` 结果标注 / 环境自检(后端检测/报告) |
| `test_server.py` | 1 | HTTP 端点 + 运行流(另:SSE 实时流实跑验证) |

**双向 parity(det 档,本机免 key)**:`parity_sweep.py` → `7 run, 3 pass, 4 skipped`。
**整条系统链路(早前已实测)**:Wolfram `LLMGraph` spec → `wlg2json` → IR → runtime,端到端闭环。

## 对照官方文档(`LLMGraph.pdf` / `LLMGraphSubmit.pdf` / `LLMFunctions.pdf`)

`LLMFunctions.pdf`(家族指南)印证:这是一组**各自独立的函数/帮助页**。对照实现也**分模块**——
`core.py`(LLMGraph)、`submit.py`(LLMGraphSubmit)、`prompts.py`(LLMPrompt/TemplateObject)、
`backends.py`(服务 + LLMConfiguration)——不挤在一个文件。

**已对齐**(逐项见 [`design/02-llmgraph-ir.md`](design/02-llmgraph-ir.md) 对照表):

- `LLMGraph` 编程模型 + 全部示例语义:节点三类型 + nodespec 全键、`ListableLLMFunction`、
  条件/`CanceledNode`、失败传播、覆盖、`Automatic/All/单节点/列表/Graph/LLMGraph`(含部分形)、单输入裸值。
- 提示规格对照(字符串列表 / `LLMPrompt` 本地库 / `TemplateObject`)。
- `LLMConfiguration`(图级 `llm_config=` + 节点级:temperature/max_tokens/stop/top_p/system)。
- `Authentication`(`{"api_key"}`/`{"env"}`/默认环境)。
- `Information` 多形态(Properties/Nodes/Graph/LLMEvaluator)。
- **`LLMGraphSubmit`(异步)**:`Task` + 全套 `HandlerFunctions` 事件 + `HandlerFunctionsKeys` + `target`(`submit.py`,见 [`design/07-llmgraphsubmit.md`](design/07-llmgraphsubmit.md))。

**仍有的小差距**:

1. `LLMConfiguration` 的 **tools/工具调用**(`LLMTool`)未接;`Authentication` 的
   `SystemCredential`/`ServiceObject` 走环境回退(WL 专有)。
2. `Information[g,"Nodes"]` 返回 dict(非 Wolfram `Dataset` 对象);`"Graph"` 返回结构(非 `Graph` 对象)。
3. **流式**:`claude-cli` 已实现(token→SSE→前端);LangChain backend(anthropic/openai)的流式
   路径与 monitor 同用时签名待统一。
4. `LLMGraphSubmit` 的**惰性祖先**(Wolfram 只跑到最近已知结果)未做;同一图实例一次一跑。
5. **环路 / 服务接口(供 Wolfram 反向调用)** —— 超集扩展,未做。

## 下一步

优先级见 [`drafts/roadmap.md`](drafts/roadmap.md)。近期候选:
**①** `LLMSynthesizeSubmit`(异步生成)+ `wolfram_agents chat`(ChatObject)——继续按家族补成员;
**②** `LLMTool` 工具调用(补 `LLMConfiguration` 最后一块,接 `wolfram_agents` 子命令);
**③** 统一 LangChain backend 流式(与 claude-cli 一致)。
