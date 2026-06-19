# 架构分层

> 状态:设计稿。最后更新:2026-06-19。

## 三层(各管一件事)

```
┌─────────────────────────────────────────────────────────┐
│ ① LLMGraph IR（规格 / 知识）                              │
│   声明式图：命名节点 + 自动推断依赖 + 并发语义            │
│   只"描述"，不关心谁来跑。                                │
│   表达形式：Wolfram <|...|> / 我们的 JSON / Python dict   │
├─────────────────────────────────────────────────────────┤
│ ② Runtime（编译器 + 执行器）= 库                          │
│   把 IR 编译成可执行物并跑起来。后端可换：               │
│   现在 = LangGraph；理论上也可 = Wolfram 内核。           │
├─────────────────────────────────────────────────────────┤
│ ③ 前端（怎么调用 Runtime）                                │
│   Python API / CLI / （将来）HTTP / Socket / MCP          │
│   CLI 只是其中一个前端，不是核心。                        │
└─────────────────────────────────────────────────────────┘
```

**关键原则:库是主、前端是从。** Runtime 是可 `import` 的核心价值;CLI / 服务只是它的消费者。

## 中枢辐射模型(IR 为 lingua franca)

```
   Wolfram LLMGraph (.nb/.wl)
         │ transpile（文本/WXF，免内核 → 覆盖"无损子集"）
         ▼
社区/LangGraph ◀──▶  LLMGraph IR (JSON)  ◀──▶ 其他版本
                         │ 中枢
                         ├─▶ 执行：Runtime (LangGraph，免授权)
                         └─▶ AI 辅助迁移：复杂/有损图 → LLM 转简化版
   ───────（可选：运行期互操作通道，见 03 文档）───────
```

## 许可边界(免费层 vs 计算层)

| 层 | 是否需要 Wolfram | 内容 |
|---|---|---|
| **免费层** | 否 | LLMGraph 结构 + LLM 节点 + LangGraph 扩展(环路/流式/恢复) |
| **计算层** | 是(仅这些节点) | 回调 WolframEngine 的计算节点 |

"能干净免内核抽取的子集"≈"免费层子集",边界自洽。

## CLI vs Runtime —— 定位结论

之前的纠结("CLI 是否多此一举")结论:**不冗余,但可选。**

- **Runtime(库)= 核心**:超集引擎,`import wolfram_llmgraph`。
- **CLI = 零基建的调用/集成面**:headless/CI/管道,以及 **Wolfram 通过 `RunProcess`/`StartProcess` shell-out 调我们**(与我们 shell-out 调 `claude` 对称)。
- **HTTP / MCP 服务 = 正式服务形态**(按需再上)。

## 后端抽象

LLM 后端可插拔(见 `src/wolfram_llmgraph/backends.py`):

| backend | 认证方式 | 需要 |
|---|---|---|
| `anthropic`(默认) | langchain-anthropic → API | `ANTHROPIC_API_KEY` |
| `openai` | langchain-openai → API | `OPENAI_API_KEY` |
| `claude-cli` | 调本机**已账号登录**的 `claude -p`(stdin 传 prompt) | 装好并登录的 Claude Code CLI |
| `qwen` | langchain-openai → DashScope | `DASHSCOPE_API_KEY` |
| `qwen-tokenplan` | langchain-openai → DashScope(token plan) | `DASHSCOPE_TOKENPLAN_API_KEY` |
| `deepseek` | langchain-openai → DeepSeek API | `DEEPSEEK_API_KEY` |

### 节点级 backend 切换

backend 可在**图级**(`LLMGraph(backend=...)` / IR 顶层 `"backend"`)和**节点级**(`{"prompt":..., "backend":"openai"}`)两层设置。节点级覆盖图级,图级覆盖默认值(`anthropic`)。同一张图的不同节点可路由到不同 provider:

```json
{
  "nodes": {
    "Draft":  "Write a poem about `Topic`",
    "Review": {"prompt": "Critique: `Draft`", "backend": "openai", "model": "gpt-4o"}
  }
}
```

> 本机现状:无 `ANTHROPIC_API_KEY`,走 `claude-cli` 后端。详见项目记忆 `claude-access-via-cli`。

## 执行引擎实现要点

- IR 编译为 LangGraph `StateGraph`;**动态生成 per-field 状态 schema**(每个节点/输入一个 channel),从而让相互独立的节点能并发写入(单一 dict channel 会因"每步只能一次写入"而冲突)。
- 依赖 = 边;无依赖节点连 `START`;sink 节点连 `END`。
- 并发由 LangGraph 的 superstep 调度;扇入节点等所有父节点完成。
