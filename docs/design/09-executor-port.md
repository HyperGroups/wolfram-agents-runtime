# Executor 端口 —— 把"超集"做成可测、可拆的架构契约

> 状态:已实现 MVP。最后更新:2026-06-20。

## 动机:别让 LangGraph 渗进语义层

定位是 **LLMGraph 的外部超集**:Wolfram 语义是**子集**,额外能力(重试/检查点/环路…)是
**可加可拆的外圈**。风险在于——一旦 LangGraph(或某个完备 agents runtime)的机制渗进语义层,
"子集关系"就破了,就成了"另一个被 LangGraph 绑死的东西",不再是超集。

为防这件事,在**语义**与**执行**之间切一刀:**Executor 端口**。

## 切法

`LLMGraph` 只负责**语义 + IR + 产出中性执行计划**;执行交给一个可替换的 `Executor`:

```
LLMGraph(语义核)
  ├─ 依赖推断 / 分类 / sinks / outputs / 条件/失败 语义      ← 零 LangGraph
  └─ _make_plan() → ExecutionPlan{runners, node_deps, sinks, state_fields}
                         │  runner 的中性契约:async (state) -> {name: value}
                         ▼
   Executor.run(plan, state) -> 结果
     ├─ ReferenceExecutor   零依赖,拓扑波次 + asyncio 并发(忠实子集)
     └─ LangGraphExecutor   编译成 StateGraph(超集长这边)
```

- **runner 不动**:llm/listable/wolfram/conditional/失败传播/监控 全部留在中性 runner 里
  (它们是 Wolfram 语义 + 横切监控,不是 LangGraph 的东西)。两个 executor 驱动**同一批 runner**,
  只在**调度**上不同。
- **超集只长在 LangGraph 这侧**:重试、checkpoint、动态拓扑(conditional edges/Send)、环路、
  interrupt —— 永远不回灌语义核。
- **切换**:`LLMGraph(..., executor="reference"|"langgraph"|<实例>)` 或 `$LLMGRAPH_EXECUTOR`。
  多技术选型兼容并存、可切换;主线默认暂留 `langgraph`,慢慢收敛。

## 子集 / 超集边界(明文)

| 留在中性核(两 executor 都必须有) | 只在 LangGraph adapter(超集外圈) |
|---|---|
| 依赖推断、**独立节点并发**、override、条件门 + CanceledNode、失败传播、属性选择/解包 | 重试/超时、checkpoint/恢复/time-travel、interrupt/HITL、动态拓扑/环路、持久化 state |

> 注:"独立节点能并发"是**子集**(Wolfram 文档明说),所以 ReferenceExecutor 不是串行——它按
> 拓扑波次 `asyncio.gather` 就绪节点;"并发上限/限流"才是超集。

## 契约用测试焊死(parity 内移一层)

`parity.py` 是"我们 vs Wolfram 内核";现在多一层**内部 parity:同一 IR 在 Reference vs LangGraph
两 executor 上跑,结果精确相等**(`tests/test_executors.py`,8 例,离线免 key)。这条绿就同时证明:

1. 语义核是 Wolfram 的**真子集**——它不需要 LangGraph;
2. LangGraph **确实可拆**(降级成一个 adapter);
3. 只在 LangGraph 侧出现的能力,**定义上**就是超集,漏不进子集。

`ReferenceExecutor` 是"是不是超集"的**活体证明**,不是为扛生产可靠性(它故意不做重试/checkpoint)。

## 现状与后续

- ✅ `executors.py`:`ExecutionPlan` / `Executor` 协议 / `ReferenceExecutor` / `LangGraphExecutor` /
  `get_executor`;`core.py` 的 `_make_plan` + `ainvoke` 走 executor;`langgraph_structure()` 变成
  **executor-specific**(只 LangGraph 有编译图视图),`information()` 是恒在的语义层。
- 默认仍 `langgraph`(118 测试全绿,行为不变);`reference` 全量可切换并 parity 通过。
- 后续(都长在 LangGraph adapter,不污染核):节点级**重试/超时**、**checkpoint/恢复**、
  动态拓扑/环路。可选:把 `langgraph` 降为 `extras`(`pip install …[langgraph]`),让"可拆"落到依赖上;
  把 executor adapter 拆进子包 `wolfram_llmgraph.executors`(已是独立模块,进一步可独立成包)。

## 参考
- 运行时该补哪些(重试/持久化/沙箱/限流…)→ 见 roadmap;它们都归 LangGraph adapter 侧。
- 监控事件源(两 executor 共用)→ [`06-runtime-monitor.md`](06-runtime-monitor.md)
