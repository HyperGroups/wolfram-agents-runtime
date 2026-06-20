# 文档索引

`wolfram-agents-runtime` —— Wolfram **LLM 家族**的外部运行时(`wolfram_agents` 主入口),
`LLMGraph` 是其中一个能力组,非全部。见 [`design/08-agents-cli.md`](design/08-agents-cli.md)。

> 📌 **当前进展看 [`STATUS.md`](STATUS.md)**(权威现状快照:能力清单、节点矩阵、
> 测试与双向验证结果、已知缺口)。本页是文档导航与代码地图。

## 一分钟理解

- **是什么**:用 LangGraph 复刻 Wolfram `LLMGraph` 的编程模型(声明式图 + 依赖自动推断 + 并发),作为更强、可独立分发、免授权的"瘦引擎";同时把图当可移植知识,在各生态间迁移复用。
- **为什么**:Wolfram 原生 `LLMGraph` 执行受限、且默认绑 Wolfram Cloud / LLM Kit(账号+订阅+联网);WolframEngine 又是商业授权。我们把**编排/LLM 从引擎里解耦**出来。
- **三层依赖**:LLM 编排+调用 → 只要 provider key(零 Wolfram-Cloud 依赖);Wolfram 计算节点 → 才需引擎许可(按需子进程);Wolfram AI Access/LLM Kit → **全程可选**。

## 设计文档(docs/design)

| 文档 | 内容 |
|---|---|
| [00-overview](design/00-overview.md) | 定位、价值线(迁移复用 / 超集执行)、非目标、两种用户模式 |
| [01-architecture](design/01-architecture.md) | 三层架构(IR / Runtime / 前端)、中枢辐射、许可边界、CLI vs Runtime |
| [02-llmgraph-ir](design/02-llmgraph-ir.md) | IR(JSON)规格、节点类型、依赖推断、Wolfram 兼容子集 vs 超集扩展 |
| [03-wolfram-integration](design/03-wolfram-integration.md) | 交互通道全景(实测)、**LLM 鉴权三模式 + cloud-optional 原则**、MCP/CAG |
| [05-dual-engine-parity](design/05-dual-engine-parity.md) | 双引擎并行验证(瘦引擎 vs Wolfram 原生)、parity 比对分层 |
| [06-runtime-monitor](design/06-runtime-monitor.md) | 运行时监控:Wolfram 监控面实测 + 观测层 + 零依赖 HTTP/SSE 服务 + 前端 web 应用 |
| [07-llmgraphsubmit](design/07-llmgraphsubmit.md) | 异步提交 `LLMGraphSubmit`(独立函数/模块):Task + HandlerFunctions 事件,架在 monitor 事件流上 |
| [08-agents-cli](design/08-agents-cli.md) | **从 agents 出发的 CLI 主入口 `wolfram_agents`**:参照 LLM 家族指南,把 LLMGraph/Synthesize/Prompt/… 编成命令组,每成员独立模块 |
| [09-executor-port](design/09-executor-port.md) | **Executor 端口**:语义核 + 可切换执行器(零依赖 Reference / LangGraph),把"超集=子集+可拆"做成内部 parity 测试契约 |

## 草稿 / 演进(docs/drafts)

| 文档 | 内容 |
|---|---|
| [migration-and-transpilers](drafts/migration-and-transpilers.md) | 迁移主线、中枢图、三层迁移、转译器矩阵 |
| [roadmap](drafts/roadmap.md) | **前瞻计划**(下一步 / 延后);现状见 [`STATUS.md`](STATUS.md) |

## 代码与示例地图

```
src/wolfram_llmgraph/      LLMGraph 库(家族成员各自一个模块)
  core.py                  LLMGraph 语义核:解析/依赖推断/属性/条件/失败传播/产出 ExecutionPlan
  executors.py             Executor 端口:ReferenceExecutor(零依赖)/ LangGraphExecutor / get_executor
  backends.py              LLM 后端:anthropic · openai · claude-cli · qwen · qwen-tokenplan · deepseek(节点级可切)
  compute.py               Wolfram 计算节点:{"wolfram":"<WL>"} 经 wolframscript 子进程求值
  monitor.py               观测层:RunMonitor,节点生命周期事件 + 计时 + token 用量 + 订阅
  prompts.py               提示规格对照:LLMPrompt / TemplateObject / Slot / PromptLibrary
  submit.py                异步提交 LLMGraphSubmit:Task + HandlerFunctions 事件
  synthesize.py            LLMSynthesize:一次性文本生成
  planner.py               NL→图规划:plan_graph/run_task/check_runnable(`wolfram_agents do` 的实现)
  loaders.py  cli.py       JSON 加载 · CLI(llmgraph run/info/serve/doctor,.env 自动加载)
  server.py                零依赖 HTTP+SSE 监控服务(/api/graph·state·events·run)
  webapp/index.html        前端单文件 web 应用:SVG DAG 实时着色 + 进度 + 详情 + 事件流
  doctor.py                环境自检:后端凭据/工具可用性(--json/--fix 供 agent)
src/wolfram_agents/        ★ 伞包(系统入口,依赖 wolfram_llmgraph 库)
  cli.py                   wolfram_agents 家族主入口(do/synthesize/graph/prompt/backends/doctor)
  __init__.py              家族公开 API 门面(from wolfram_agents import LLMGraph, LLMSynthesize)
tools/
  wlg2json.wls             转译器:Wolfram LLMGraph spec → IR JSON(无损子集)
  run_native.wls           在 Wolfram 原生 LLMGraph 上跑 IR(复用 llm.wls 的 ask[])
  parity.py                双引擎 parity:同一 IR 两边各跑,结构精确 + 确定性节点值精确 + LLM 并列
  parity_sweep.py          一键扫描 examples/wolfram-docs/ 全部官方示例做双向测试
examples/
  *.json                   IR 示例(bestpoem / renga)
  mixed_wolfram.json       混合图:LLM → Wolfram 计算节点 → LLM
  python_api.py            Python API(混合 LLM + 代码节点)
  wolfram-docs/            ★ 官方 LLMGraph.nb 示例移植:每例 .json + 文档页 .md + 双向测试
  wolfram/
    llm.wls                ★ Wolfram 侧 cloud-optional 统一 LLM 接入(ask[])
    deepseek_config.wls    Wolfram 原生模式 B 示例(注册服务,直连,免云)
    renga.wls              真实 Wolfram LLMGraph(claude 后端)
    renga_native.wls       规范 spec(供转译器)
    README.md              Wolfram 侧示例与流水线说明
```

## 快速上手

```bash
# 瘦引擎(LangGraph),选后端
llmgraph run examples/renga.json -i Topic=spring --backend claude-cli
llmgraph run examples/renga.json -i Topic=spring --backend qwen      # 需 DASHSCOPE_API_KEY

# Wolfram 原生跑同一张图(cloud-optional,默认绕开 Wolfram Cloud)
wolframscript -file tools/run_native.wls examples/renga.json input.json out.json claude

# 双引擎互相验证
python tools/parity.py examples/renga.json --input '{"Topic":"autumn"}' --backend claude-cli

# Wolfram spec → IR
wolframscript -file tools/wlg2json.wls examples/wolfram/renga_native.wls out.json
```

密钥见 [`../.env.example`](../.env.example)(`.env` 已 gitignore,CLI 自动加载)。
