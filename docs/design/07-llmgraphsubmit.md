# 异步提交 `LLMGraphSubmit`(独立函数/独立模块)

> 状态:已实现 MVP。最后更新:2026-06-20。
> 对照官方 `LLMGraphSubmit.pdf`(它是**独立的 Wolfram 函数 + 独立帮助页**)。

`LLMGraph` 在 Wolfram 里有个独立的异步伴随函数 `LLMGraphSubmit` —— 提交一次异步求值,
返回 **`TaskObject`**,执行期通过 `HandlerFunctions` 发出事件。我们**独立成一个模块**
`src/wolfram_llmgraph/submit.py`(不挤进 `core.py`),并**架在已有的 `RunMonitor` 事件流之上**。

## 对照表

| Wolfram | 本项目 |
|---|---|
| `LLMGraphSubmit[graph, input, target]` → `TaskObject` | `LLMGraphSubmit(graph, input, target)` / `graph.submit(...)` → `Task` |
| `target` = `Automatic` / `All` / `{namei}` | `"Automatic"` / `"All"` / `["a","b"]` / 单节点名 |
| `TaskWait[task]` | `task.wait()` / `task_wait(task)` |
| `TaskObject` 状态 | `task.status`(Running→Finished→Removed)、`task.uuid` |
| 图事件 `NodeSubmitted/NodeSynthesized/NodeCanceled/NodeFailed/ResultGenerated` | 同名事件(由 monitor 的 node 生命周期翻译) |
| 任务事件 `TaskStarted/TaskStatusChanged/TaskFinished/TaskRemoved/FailureOccurred` | 同名事件 |
| `HandlerFunctions -> f` 或 `<|"event"->f,...|>` | `handlers=` 单 callable 或 `{event: callable}` |
| `HandlerFunctionsKeys`(EventName/Failure/CurrentNode/NodeResult/LLMGraph/GraphResults/Task/TaskStatus / All / Automatic / {keys}) | `handler_keys=` 同集合;`"All"/"Automatic"`=全给,字符串/列表=子集 |
| 未到位的值 = `Missing["NotAvailable"]` | `"Missing[NotAvailable]"` |

## 事件映射(monitor → LLMGraphSubmit)

```
run_start                      → TaskStarted + TaskStatusChanged(Running)
node.status = running          → NodeSubmitted
node.status = done             → NodeSynthesized   (NodeResult = 节点输出预览)
node.status = canceled         → NodeCanceled      (ConditionalNode test 为假)
node.status = error            → NodeFailed        (含失败依赖传播 FailedNode)
run_end                        → ResultGenerated + TaskFinished + TaskRemoved + TaskStatusChanged
worker 抛异常                  → FailureOccurred
```

线程模型:一个 worker 线程跑 `graph(input,"All")`(monitor 在其中发事件),一个 consumer
线程从 monitor 订阅队列读事件、翻译并**异步触发 handlers**(与 Wolfram 一致,handler 在后台触发)。

## 用法

```python
from wolfram_llmgraph import LLMGraph, LLMGraphSubmit

g = LLMGraph({"haiku": "haiku about `Topic`",
              "complete": "extend `haiku`"})

results = {}
task = g.submit({"Topic": "spring"}, handlers={
    "NodeSynthesized": lambda e: print("done:", e["CurrentNode"]),
    "TaskFinished":    lambda e: results.update(e["GraphResults"]),
})
task.wait()                 # TaskWait
task.result()               # 单输出解包;否则按 target 的关联
task.graph_results()        # 按 target 的结果关联("GraphResults" 键)
```

## 与监控/前端的关系

同一套 monitor 事件既驱动 Web 监控(`server.py` + `webapp/`),也驱动 `LLMGraphSubmit` 的
HandlerFunctions —— 一个事件源,两个消费者。后续可让 Web 端直接展示 submit 任务。

## 已知差异

- 流式 `NodeResult` 用节点输出**预览**(截断字符串);精确值在 `GraphResults`/`result()`。
- 同一 graph 实例**一次一跑**(借用其 monitor 槽位);并发多任务需各自图实例。
- `target` 的**惰性祖先**(Wolfram 只跑到最近已知结果)未做:我们求值全图后按 target 取子集。

## 参考
- 同步版 → [`02-llmgraph-ir.md`](02-llmgraph-ir.md) · 监控/事件源 → [`06-runtime-monitor.md`](06-runtime-monitor.md)
- LLM 家族全景 → 见 `LLMFunctions.pdf`(指南页:LLMFunction / LLMGraph(Submit) / LLMSynthesize(Submit) / LLMPrompt / LLMConfiguration / LLMTool …,各自独立)
