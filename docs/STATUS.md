# 当前进展(STATUS)

> 快照日期:2026-06-19。本文件是**现状的权威记录**;前瞻计划见
> [`drafts/roadmap.md`](drafts/roadmap.md)。
> 约定:**「已实测」= 本机内核/测试实跑确认;「未重跑」= 早前验证过、本轮未再跑;
> 「设计」= 仅文档、未落地。** 不把推断当确认。

## 一句话

Wolfram `LLMGraph` 编程模型的 **LangGraph 瘦运行时**已可用:声明式图 + 依赖自动推断 +
并发调度,支持 LLM / 代码 / Wolfram 计算 / **条件** / **ListableLLM**五类节点,**6 个 LLM 后端 + 节点级 backend 切换**(同一张图可混合不同 provider),**后端自动检测(auto 模式)** + 手动模式,并与
Wolfram 原生 `LLMGraph` 做**双向 parity 互验**。25 个离线测试全过;3 个官方文档示例在
两个引擎上**精确值对齐(免 key、免网络)**。前端 web 应用全面优化(SVG pan/zoom、SSE 自动重连、亮暗主题、**流式 token 显示、成本估算、多运行对比**)。79 个测试全部通过。

## 能力清单

| 模块 | 文件 | 状态 | 说明 |
|---|---|---|---|
| 核心引擎 | `src/wolfram_llmgraph/core.py` | ✅ 已实测 | 解析 / 依赖推断 / 动态 state schema / 编译 LangGraph / 并发 / 属性选择 / 覆盖 / 条件节点 / `information()` / **ListableLLMFunction(map/扇出)** / **失败传播(FailedNode)** |
| Wolfram 计算节点 | `compute.py` | ✅ 已实测 | `{"wolfram":"<WL>"}` 经 `wolframscript` 子进程在内核求值,依赖用 `deps["name"]`;失败时返回 `FailedNode` 而非抛错 |
| LLM 后端 | `backends.py` | ✅ 已实测 | 6 个:`anthropic` · `openai` · `claude-cli` · `qwen` · `qwen-tokenplan` · `deepseek`。**节点级切换**:`{"prompt":..., "backend":"openai"}` 覆盖图级默认;同一张图可混合 provider。**后端自动检测**:`--backend auto`(默认)根据环境变量自动选择可用 backend;`--backend-strict` 强制使用指定 backend |
| IR + JSON 加载 | `loaders.py` | ✅ 已实测 | 见 [`design/02-llmgraph-ir.md`](design/02-llmgraph-ir.md) |
| CLI | `cli.py` | ✅ 已实测 | `llmgraph run` / `info` / `serve`,`--input/-i/--prop/--model/--backend/--backend-strict`,`.env` 自动加载,UTF-8 |
| **运行时监控** | `monitor.py` + `server.py` + `webapp/index.html` | ✅ 已实测 | 节点生命周期事件(pending→running→done/canceled/skipped/error)+ 计时 + token 用量;零依赖 HTTP+SSE 服务 + 单文件前端 DAG 实时可视化。**两层视图**:LLMGraph 语义层(`/api/graph`,含输入顶点/输出徽标/类型色) + LangGraph 运行层(`/api/langgraph`,编译后 `__start__→…→__end__` + 官方 `draw_mermaid()`)。**前端全面优化**:SVG pan/zoom、SSE 自动重连、运行状态绑定、事件日志上限、竞态修复、边标签自适应、历史分页、JSON 实时校验、键盘快捷键、亮暗主题等。见 [`design/06-runtime-monitor.md`](design/06-runtime-monitor.md) |
| 双引擎 parity | `tools/parity.py` + `run_native.wls` | ✅ 已实测 | 同一 IR 两引擎各跑:结构精确 + 确定性节点值精确 + LLM 并列。**超时守护**:`--timeout` 参数防止孤儿内核锁 license |
| 文档示例双向测试 | `tools/parity_sweep.py` + `examples/wolfram-docs/` | ✅ 已实测 | 官方示例移植 + 一键扫描互验 |
| WL→IR 转译器 | `tools/wlg2json.wls` | ✅ 已实测 | Wolfram `LLMGraph` spec → IR(无损子集) |
| Cloud-optional 接入层 | `examples/wolfram/llm.wls` | ✅ 已实测 | 统一 `ask[]`,默认绕开 Wolfram Cloud |

## 节点类型支持矩阵

| 节点 | Wolfram 形式 | 我们的 IR | parity 档 |
|---|---|---|---|
| LLM | `"prompt `Slot`"` / `LLMFunction` / `StringTemplate` / 节点级 `LLMEvaluator` | `"prompt"` 或 `{"prompt":...,"model":...,"backend":...}` | 结构(LLM 非确定) |
| **ListableLLM** | `ListableLLMFunction["prompt `Slot`"]` | `{"listable_llm":"...","input":[...]}` — 并行 map 过列表输入 | 结构(LLM 非确定) |
| 代码(Python) | `EvaluationFunction -> (f &)` | `callable` 或 `{"fn":callable,"input":[...]}` | 仅瘦引擎 |
| Wolfram 计算 | `EvaluationFunction -> (WL &)` | `{"wolfram":"<WL>","input":[...]}` | **确定性·精确值** |
| 条件 `ConditionalNode` | `<|EvaluationFunction, TestFunction, InputTestFunction|>` | 任意节点 + `"test"` + `"test_input"` | **确定性·精确值** |
| 属性选择 | `g[in,"All"/"name"/"LLMGraph"]` | `g(in,"All"/"name"/[...]/"Graph")` | — |
| 中间覆盖 | `g[<|"Node"->val,...|>]` | `g({"Node":val,...})` | — |
| 失败传播 | `$Failed` 沿依赖传播 / 被取消节点下游 | `FailedNode` / `CanceledNode` 自动传播到下游节点 | — |

**尚未支持**:流式、环路、服务接口。详见[下方缺口](#已知差异与缺口)。

## 官方文档示例移植清单

来自本机 15.0 `LLMGraph.nb`(脚本 `scripts/dump_llmgraph_examples.wl` 抽取)。每例自带独立
`.json` + 文档页 `.md`,见 [`../examples/wolfram-docs/`](../examples/wolfram-docs/README.md)。

| 示例 | 来源 cell | 档 | 双向测试结果 |
|---|---|---|---|
| `doubling`(`2*#Argument`) | 15–16 | det | ✅ 已实测:`42 == 42` |
| `output_nodes`(三节点 DAG) | 21–29 | det | ✅ 已实测:三节点值全等 |
| `conditioned`(`ConditionalNode`) | 17–19 | det | ✅ 已实测:真→`"NodeHasRun"`、假→`Missing[CanceledNode,…]`,两支精确 |
| `whatis`(LLMSubmission 单节点) | 8–11 | llm | 结构 parity(本轮未重跑) |
| `restyle`(LLM→`ToUpperCase`) | 94 | llm | 结构 parity(本轮未重跑) |
| `bestpoem` / `renga`(根目录) | 2–7 | llm | 结构 parity(早前 PASS,本轮未重跑) |

`parity_sweep.py` 默认只跑 det 档(本机、免 key);`--with-llm` 才跑 llm 档(需共用后端)。

## 测试与双向验证(已实测)

- **离线单测 79 passed**:依赖推断、输入分类、并发、单输出解包、`All`、代码节点、中间覆盖、
  Wolfram 节点解析、属性选择(单节点/列表/`Graph`/未知报错)、条件节点(真/假/边)、
  文档示例静态结构 7 例、**监控层 6 例(状态/覆盖/事件流/错误/流式/成本)**、**后端层 16 例(成本估算/自动检测/验证)**、**加载器 18 例(from_dict/load_json/所有字段)**、**笔记本管理 11 例(创建/列表/激活/保存/加载/注册表)**。
  无需 key/网络。`pytest -q`。另:监控 SSE 实时流实跑验证(`run_start→node×N→run_end`)。
- **双向 parity(det 档,本机免 key)**:`parity_sweep.py` → `7 run, 3 pass, 0 not-pass, 4 skipped`
  (`doubling`/`output_nodes`/`conditioned` 三档 `PARITY: PASS`;4 个 llm 档 SKIP)。
- **整条系统链路(早前已实测)**:Wolfram `LLMGraph` spec → `wlg2json` → IR → runtime 执行,端到端闭环。

## 已知差异与缺口

1. **流式 / 环路** —— 超集扩展,未做。
2. **服务接口** —— HTTP / `ExternalEvaluate` 入口供 Wolfram 反向调用,未做。

## 下一步

优先级与计划见 [`drafts/roadmap.md`](drafts/roadmap.md)。近期候选:
**①** 流式输出(P1-4);
**②** 成本估算(P1-8);
**③** 多运行对比(P1-5)。
