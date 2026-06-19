# CorrectWorkflow 执行模式对比

## Wolfram 原始代码

```wolfram
CorrectWorkflow = LLMGraph[<|
  "Decide" -> "Decide if the following contains errors...",
  "Review" -> <|
    "LLMFunction" -> "List any errors...",
    "TestFunction" -> Function@StringContainsQ[#Decide, "Errors"]
  |>,
  "Rewrite" -> <|
    "LLMFunction" -> "Rewrite the text...",
    "TestFunction" -> Function@StringQ[#Review]
  |>,
  "Final" -> <|
    "EvaluationFunction" -> Function[...],
    "Inputs" -> {"Rewrite", "Input"}
  |>
|>]
```

## 两种执行模式

### Sequential 模式（默认）

**语义**：先评估 test，再执行 LLM

```
Input → Decide (2.0s)
           ↓
        [test: "Errors" in Decide?] → true
           ↓
        Review (4.9s)
           ↓
        [test: isinstance(Review, str)?] → true
           ↓
        Rewrite (0.5s)
           ↓
        Final
```

**特点**：
- 严格串行执行
- 如果 test 失败，不执行 LLM（节省成本）
- 总耗时：7.45s

**适用场景**：
- test 评估成本低
- 希望避免不必要的 LLM 调用
- 对成本敏感

### Speculative 模式（Wolfram 语义）

**语义**：先执行 LLM，再评估 test，如果 test 失败则丢弃结果

```
Input ──┬── Decide (2.0s)
        │
        └── Review (4.2s, 并行开始)
              ↓
           [test: "Errors" in Decide?] → false → CanceledNode
              ↓
           Rewrite (canceled)
              ↓
           Final
```

**特点**：
- LLM 调用并行执行
- 即使 test 失败，LLM 已经执行（浪费成本）
- 总耗时：6.21s（更快）

**适用场景**：
- 希望最大化并行度
- LLM 调用延迟高
- test 经常通过

## 性能对比

| 模式 | 总耗时 | Decide | Review | Rewrite | 并行度 |
|------|--------|--------|--------|---------|--------|
| Sequential | 7.45s | 2.0s | 4.9s | 0.5s | 串行 |
| Speculative | 6.21s | 2.0s | 4.2s | 0.5s | 并行 |

**加速比**：1.20x（Speculative 快 20%）

## 使用方法

### Python API

```python
from wolfram_llmgraph import LLMGraph

# Sequential 模式（默认）
graph = LLMGraph({
    "Review": {
        "prompt": "...",
        "test": lambda Decide: "Errors" in str(Decide),
    },
})

# Speculative 模式（Wolfram 语义）
graph = LLMGraph({
    "Review": {
        "prompt": "...",
        "test": lambda Decide: "Errors" in str(Decide),
    },
}, speculative=True)
```

### 命令行

```bash
# Sequential 模式
python examples/correct_workflow_sequential.py --port 8765

# Speculative 模式
python examples/correct_workflow_speculative.py --port 8765
```

## 实现细节

### Sequential 模式

1. 图结构包含所有依赖（eval_deps + test_deps）
2. 节点等待所有依赖完成
3. 执行时：先评估 test，如果通过再执行 LLM

```python
async def gated(state: dict) -> dict:
    if not await self._eval_test(nd, state):
        return {nd.name: CanceledNode(nd.name)}
    return await inner(state)  # 只在 test 通过后执行
```

### Speculative 模式

1. 图结构只包含 eval_deps（test_deps 不参与调度）
2. 节点只等待 eval_deps 完成
3. 执行时：先执行 LLM，再评估 test，如果失败则丢弃结果

```python
async def speculative_gated(state: dict) -> dict:
    result = await inner(state)  # 先执行 LLM
    if not await self._eval_test(nd, state):
        return {nd.name: CanceledNode(nd.name)}  # test 失败，丢弃结果
    return result  # test 通过，保留结果
```

## 选择建议

| 场景 | 推荐模式 | 原因 |
|------|---------|------|
| 成本敏感 | Sequential | 避免不必要的 LLM 调用 |
| 延迟敏感 | Speculative | 最大化并行度 |
| test 经常失败 | Sequential | 节省 LLM 成本 |
| test 经常通过 | Speculative | 利用并行加速 |
| 与 Wolfram 兼容 | Speculative | 完全匹配 Wolfram 语义 |
