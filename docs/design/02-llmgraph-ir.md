# LLMGraph IR 规格

> 状态:设计稿(部分已实现)。最后更新:2026-06-19。

IR 是项目的中枢:既是迁移目标格式,也是 Runtime 的输入。下面区分**已实现** ✅ 与**设计中** 🔲。

## JSON 形态

```json
{
  "nodes": {
    "Poet1": "write a short poem about summer",
    "Poet2": "write a haiku about winter",
    "Judge": "Choose the best:\n1) `Poet1`\n2) `Poet2`"
  },
  "output": ["Judge"],
  "model": "claude-opus-4-8",
  "backend": "anthropic"
}
```

- `nodes`(必填):名字 → 节点规格。
- `output`(可选):输出节点列表;缺省 = sink 节点(无人依赖者)。
- `model`(可选):图级默认模型。缺省 `claude-opus-4-8`。
- `backend`(可选):图级默认 backend:`anthropic`(默认) | `openai` | `claude-cli` | `qwen` | `qwen-tokenplan` | `deepseek`。

### 节点级 backend 切换

每个节点可独立指定 `backend` 和 `model`,覆盖图级默认值。同一张图可混合不同 provider:

```json
{
  "nodes": {
    "Draft":  "Write a poem about `Topic`",
    "Review": {"prompt": "Critique this poem:\n`Draft`", "backend": "openai", "model": "gpt-4o"}
  }
}
```

`Draft` 走图级默认(如 `anthropic`),`Review` 走 OpenAI。Wolfram 原生侧(`run_native.wls`)对可映射的 backend(`openai`/`anthropic`/`deepseek`)自动生成 `LLMEvaluator -> LLMConfiguration[<|"Model" -> {service, model}|>]`;无法映射的 fallback 到 `ask[]`。

## 节点规格

| 规格 | 含义 | 状态 |
|---|---|---|
| `"prompt 字符串"` | LLM 节点;`` `Slot` `` 引用 → 依赖 | ✅ |
| Python callable | 代码节点;参数名 → 依赖 | ✅(Python API) |
| `{"prompt": "...", "model": "..."}` | 带选项的 LLM 节点 | ✅ |
| `{"prompt": "...", "model": "...", "backend": "..."}` | 节点级 provider 切换(每个节点可用不同 LLM 服务) | ✅ |
| `{"fn": callable, "input": [...]}` | 显式依赖的代码节点 | ✅(Python API) |
| `{"wolfram": "<WL 代码>", "input": [...]}` | Wolfram 计算节点(子进程回调 Engine);代码用 `deps["name"]` 取依赖,缺省自动探测 | ✅ 计算层 |
| `{..., "test": "<WL 或 callable>", "test_input": [...]}` | 条件节点(`ConditionalNode`):`test` 真才求值,否则 → `Missing[CanceledNode, name]`。任意节点可加 | ✅ |
| `{"listable": true, "prompt": "..."}` | 对列表输入并行 thread | 🔲 |

## 依赖推断规则 ✅

- **prompt 字符串**:每个 `` `Name` `` 槽位 →
  - 若 `Name` 是同图节点 → 依赖该节点;
  - 否则 → 视为运行期**输入参数**。
- **Python callable**:形参名即父节点(同样按"是节点 / 是输入参数"分类)。
- 槽位渲染:执行时把 `` `Name` `` 替换成对应结果的字符串。

## 求值语义 ✅

- `graph(input)`:`input` 是 `{输入参数名: 值}`。
- **中间节点覆盖**:`input` 里直接给某节点赋值 → 跳过其求值(bypass),下游读到该值。
- 属性选择 `graph(input, prop)`:
  - `None` / `"Automatic"` → 输出节点(单输出自动解包);
  - `"All"` → 所有节点结果;
  - `"Graph"` → 静态图结构;`"节点名"` → 单节点结果;`["a","b"]` → 仅这些节点。✅
  - 🔲 `"LLMGraph"`(带**结果**的标注图)暂未实现(我们的 `"Graph"` 只给静态结构)。

## 与 Wolfram `LLMGraph` 的对照

兼容子集(= 迁移"无损层"目标):

| Wolfram | 我们的 IR | 状态 |
|---|---|---|
| `"name" -> "prompt"`(LLMFunction) | `"name": "prompt"` | ✅ |
| `"name" -> Function[...]`(纯 WL) | `{"wolfram": "..."}` 计算节点 | ✅ |
| `<\|"EvaluationFunction"->...\|>` | `{"fn": ...}` / `{"wolfram": ...}` | ✅ |
| `<\|"LLMFunction"->...\|>` | `{"prompt": ...}` | ✅ |
| `<\|"ListableLLMFunction"->...\|>` | `{"listable": true, ...}` | 🔲 |
| `<\|"Input"->{...}\|>`(显式依赖) | `"input": [...]` | ✅ |
| `<\|"TestFunction"->...,"InputTestFunction"->...\|>`(条件) | `{"test": ..., "test_input": [...]}` | ✅ |
| `graph[in]` / `graph[in, All]` | `graph(in)` / `graph(in,"All")` | ✅ |
| 选项 `LLMEvaluator`/`Authentication`(图级) | `model`/`backend`(图级) | ✅ |
| 节点级 `LLMEvaluator`(per-node provider) | `{"prompt": "...", "model": "...", "backend": "..."}` | ✅ |

## 超集扩展(LangGraph 带来、Wolfram 内核没有)

均为 🔲 设计中,按价值排序:

1. **环路 / agent-loop**(Wolfram LLMGraph 是 DAG;LangGraph 允许环)。
2. **条件路由**(超出 TestFunction 的分支)。
3. **流式输出 + 进度**。
4. **检查点 / 可恢复 / human-in-the-loop**。
5. **工具调用节点 / ReAct agent 节点**。
6. **子图组合**。
7. ~~**多 LLM 提供方后端**~~ → 已实现 ✅(6 个:`anthropic` · `openai` · `claude-cli` · `qwen` · `qwen-tokenplan` · `deepseek`;支持节点级切换)。

> 设计约束:扩展不得破坏"无损子集"的语义——为 Wolfram 写的兼容图,在我们这儿应当原样可跑。
