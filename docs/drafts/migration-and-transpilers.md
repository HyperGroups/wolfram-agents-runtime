# 草稿:图模板迁移与转译器(主线)

> 状态:草稿 / 待细化。最后更新:2026-06-19。
> 这是项目的**主价值线**。详见 [`../design/00-overview.md`](../design/00-overview.md)。

## 核心命题

LLMGraph(以及 LangGraph 等)本质是**图模板 = 可移植的知识**。真正的实际价值点是:

> **同一张图模板在多生态间的迁移与复用**——Wolfram `LLMGraph` ⇄ 社区/LangGraph ⇄ 我们的 IR ⇄ 其他版本。

这条线**消解了"用 Python/外部框架写图,还是在 notebook 里写"的纠结**:在哪写都行,图是可迁移的模板,**IR 是中枢**,迁移是能力。

## 中枢辐射图

```
   Wolfram LLMGraph (.nb/.wl)
         │ transpile（文本/WXF，免内核 → 覆盖"无损子集"）
         ▼
社区/LangGraph ◀──▶  LLMGraph IR (JSON)  ◀──▶ 其他版本
                         │ 中枢
                         ├─▶ 执行：Runtime (LangGraph，免授权)
                         └─▶ AI 辅助迁移：复杂/有损图 → LLM 转简化版（人工复核）
```

要点:**迁移主线主要只需要"格式转换",甚至不依赖 WolframEngine、也不依赖运行期互操作通道。** 这正呼应"NB 是免授权可利用的知识"。

## 迁移分三层

| 层 | 方式 | 需要 AI? | 需要 Engine? | 对应 |
|---|---|---|---|---|
| **1. 无损迁移** | 确定性规则转换 | 否 | 否 | 纯 LLM 图(string prompt + 槽位 + 依赖结构) |
| **2. 有损 / AI 辅助** | LLM 把节点简化/近似成目标生态可跑的版本 + 标注降级点,人工复核 | 是 | 否 | 带 Wolfram `Function`/复杂计算的节点 |
| **3. 不可迁移** | 保留为"计算层"节点,运行期回调 Engine | — | 是 | 必须 Engine 的重计算 |

(此分层与 [`../design/01-architecture.md`](../design/01-architecture.md) 的"免费层 / 计算层"许可边界一致。)

## 转译器矩阵(待建)

| 方向 | 起步实现 | 状态 |
|---|---|---|
| `Wolfram LLMGraph (.nb/.wl)` → `IR` | **免内核文本解析**(覆盖无损子集);复杂情况用内核 `NotebookImport` 兜底 | 🔲 优先 |
| `IR` → `Wolfram LLMGraph` | 生成 `LLMGraph[<\|...\|>]` 代码 | 🔲 |
| `IR` → `LangGraph` | 已有编译器(`core.py`) | ✅ 半条 |
| `IR` → `社区格式`(如 LangGraph 源码 / 其他) | 代码生成 | 🔲 |
| `社区` → `IR` | 解析 | 🔲 |

## AI 迁移助手(第 2 层)

- 输入:无法无损转换的图(或其片段)。
- 输出:目标生态可跑的**简化版** + **降级清单**(哪些 Wolfram 计算被近似/占位/删除)。
- 形态:本身可以就是一张用我们 runtime 跑的 LLMGraph(吃图、吐图)。
- 必须人工复核,不保证语义等价。

## 待解问题

1. **无损子集的精确边界**:哪些 Wolfram `LLMGraph` 写法算第 1 层?(纯 string 节点 + 槽位 + `Input`/`output`/`model`?`ListableLLMFunction`/`TestFunction` 算不算?)
2. **免内核 .nb 解析的可行度**:`.nb` 是纯文本 Wolfram 表达式,提取 `LLMGraph[<|...|>]` 关联;字符串 prompt 易,嵌套 WL 难。要不要限定只解析"声明式片段"?
3. **降级语义的标注规范**:第 2 层产物如何标记 lossy,便于人工复核与回溯。
4. **往返保真度**(round-trip):`Wolfram → IR → Wolfram` 是否需要尽量保形?

## 可立即做的验证闭环

写一个真实 `LLMGraph` 放进 `.nb`/`.wl` → **免内核文本解析成 IR JSON** → 喂给 runtime 跑通。
顺带量出"免内核抽取覆盖到哪一层"。
