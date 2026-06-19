# 设计总览 / Positioning

> 状态:设计稿(随讨论演进)。最后更新:2026-06-19。

## 一句话定位

**LLMGraph 的「外部超集运行时」+「图模板迁移中枢」。**

- 语义上向下兼容 Wolfram `LLMGraph` 的编程模型;
- 底层用 LangGraph,表达力与执行能力是 Wolfram 内核版本的**超集**(更强、可扩展);
- 同时把"图"当作**可移植的知识/模板**,在 Wolfram / 社区(LangGraph 等)/ 我们的 IR 之间**互相迁移复用**。

## 背景与动机

1. **Wolfram `LLMGraph` 的模型很好,但内核里的执行偏弱**(并发/可观测/可部署/流式/环路等)。
2. **WolframEngine 是商业授权软件**,不适合作为运行时硬依赖。
3. 但 **NB / 已定义好的 `LLMGraph` 本身是「知识」**,可以脱离 Engine,转换成 JSON 等中间表示,丢到外部免授权运行时执行。

→ 结论:**把 LLMGraph 的"描述(知识)"与"执行(引擎)"解耦**。描述自由可迁移,执行交给更强的外部 runtime。

## 核心价值(两条线)

| 线 | 阶段 | 价值 | 主/次 |
|---|---|---|---|
| **模板迁移复用** | 设计期 (design-time) | 同一张图在多生态间迁移、复用;无损规则转换 + AI 辅助简化 | **主线** |
| **超集执行** | 运行期 (run-time) | 基于 LangGraph,提供 Wolfram 内核给不了的能力(环路/流式/检查点/工具/多后端) | 支撑 |

两条线的交汇点是 **LLMGraph IR(JSON)**——既是迁移的中枢格式,也是执行的输入。

## 明确的非目标

- **不**重复造 LangChain/LangGraph 的 LLM 能力本身("会调 LLM"三方都会,不构成差异化)。
- **不**要求安装 WolframEngine 才能运行图(它是可选项,不是必需品)。
- **不**追求 100% 迁移复杂 Wolfram 计算图(复杂的留在 Wolfram,见迁移分层)。

## 两种用户模式

- **模式 1:只写好 NB / 图。** 不装 Engine。我们抽取结构 + prompt → IR → 全程免授权地跑。(知识被解放,主路径)
- **模式 2:装了 WolframEngine。** 额外解锁"节点里真做 Wolfram 计算"(符号积分、拟合、知识库……),只有这些节点碰许可。

## 相关文档

- **当前进展(现状快照)→ [`../STATUS.md`](../STATUS.md)**
- 架构分层与许可边界 → [`01-architecture.md`](01-architecture.md)
- LLMGraph IR 规格与兼容子集 → [`02-llmgraph-ir.md`](02-llmgraph-ir.md)
- Wolfram 交互通道全景 → [`03-wolfram-integration.md`](03-wolfram-integration.md)
- 迁移主线与转译器草案 → [`../drafts/migration-and-transpilers.md`](../drafts/migration-and-transpilers.md)
- 路线图与现状 → [`../drafts/roadmap.md`](../drafts/roadmap.md)
