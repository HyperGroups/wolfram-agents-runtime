# 运行时监控（Runtime Monitor）

> 状态:已实现 MVP。最后更新:2026-06-19。

把 Wolfram 执行 `LLMGraph` 时**本就有的状态/监控能力**,在我们的瘦 runtime 底层补齐,
并用一个**零依赖的前端 web 应用**实时呈现。

## Wolfram 侧有什么(本机内核实测,`scripts/probe_monitoring.wl`)

| Wolfram 能力 | 实测证据 |
|---|---|
| **图级进度面板** | 同步执行时显示 `Computing nodes [====] Elapsed time Ns`(已完成节点数/总数 + 耗时);底层 `$ProgressReporting=Automatic` + `ProgressIndicator` |
| **节点级依赖状态** | 每个节点内部记 **`PendingDependencies`**(尚未满足的依赖,随完成而收缩)——这就是"就绪/等待"态 |
| **节点类型区分** | 内部 vertex 类型 `nodeInput`/`nodeLLM`/`nodeLLMList`/`nodeWLEval`(输入/LLM/listable-LLM/WL 计算),渲染上即有别 |
| **异步句柄** | `LLMGraphSubmit[graph, input, target]` 异步求值,返回可监控的句柄 |
| **Token 用量** | `ChatObject` 的 `Usage`(`Quantity[n,"Tokens"]`) |

→ 结论:监控不是我们新发明的,是**把 Wolfram 已有的"进度 + 依赖态 + 节点类型 + 用量"做成结构化、可流式订阅的事件**。

## 底层:观测层(`src/wolfram_llmgraph/monitor.py`)

`RunMonitor` 挂到 `LLMGraph(monitor=…)`。执行时每个节点经历:

```
pending ──▶ running ──▶ done | canceled | skipped | error
```

- **pending**:等待依赖(对应 Wolfram `PendingDependencies` 非空)。
- **running / done**:开始/完成,记 `started`/`ended`/`duration`/`preview`(输出截断预览)。
- **canceled**:条件节点 `test` 为假(`CanceledNode` → `Missing[CanceledNode,name]`)。
- **skipped**:被输入直接覆盖(中间节点 bypass)。
- **error**:节点抛错,记 `error`。
- **usage**:LLM 节点尽力抓 token 用量(LangChain `usage_metadata`/`response_metadata`,对应 Wolfram `Usage`)。

`RunMonitor` 维护**实时快照**(图结构 + 每节点记录 + 进度 + 耗时)并把每次状态跃迁**推给订阅者**
(线程安全:引擎在 asyncio 线程发事件,SSE 订阅各在自己线程读)。引擎侧零侵入:不挂 monitor 时
行为完全不变(`monitor=None` 默认)。纯标准库。

## 服务:零依赖 HTTP + SSE(`server.py`)

```
GET  /                -> 监控 web 应用(webapp/index.html)
GET  /api/graph       -> 静态图结构(nodes/edges/inputs/outputs/kinds)
GET  /api/state       -> 当前运行快照
GET  /api/events      -> Server-Sent Events:实时节点生命周期流
POST /api/run {input} -> 后台起一次运行(同一图实例一次一跑)
```

图在工作线程里跑(`graph(input)` 内部 `asyncio.run`),`RunMonitor` 把事件 fan-out 给所有 SSE 订阅。
只用 `http.server`,无 FastAPI/websockets 依赖。

## 可视化:两层图(语义层 + 运行层)

一张图有两个层次,前端用 **Tab** 切换、**共享同一份实时状态**:

| 视图 | 是什么 | 数据来源 |
|---|---|---|
| **LLMGraph(语义层)** | 用户写的声明式图:节点 + 推断依赖 + **输入参数顶点** + **输出节点徽标** + 节点类型色条(`llm`/`fn`/`wolfram`)。对应 Wolfram `Information[g,"Graph"]`(含 `nodeInput` 输入顶点) | `GET /api/graph`(`Nodes`/`Edges`/`InputEdges`/`Outputs`/`NodeKinds`) |
| **LangGraph(运行层 / 编译后)** | 我们实际编译出的 `StateGraph`:`__start__ → 节点(fan-in) → __end__`,条件边虚线。这是"底下到底怎么跑的" | `GET /api/langgraph` |

两层节点同名 → 执行时状态(running/done/…)在**两个视图都实时着色**。

### LangGraph 自带可视化框架吗?——有

实测本机版本:编译后的图 `compiled.get_graph()` 返回 `Graph`,暴露 `.nodes`/`.edges`,并能
`draw_mermaid()`(Mermaid 流程图文本)/`draw_mermaid_png()`/`draw_ascii()`。我们:

- 直接取 `get_graph()` 的 `nodes/edges` 用**自家 SVG 渲染**(风格统一、可叠加实时状态);
- 同时把 LangGraph **官方 `draw_mermaid()` 文本**透出到侧栏(可一键复制),既答"框架"之问,也方便贴到任何 Mermaid 渲染器。

`langgraph_structure()`(`core.py`)封装了这层:`{nodes, edges, mermaid}`。

## 前端:单文件 web 应用(`webapp/index.html`)

纯 vanilla JS + SVG,无构建、无 npm、无 CDN:

### 核心功能
- **两层 DAG 画布**:最长路径分层布局;节点按状态着色 + `running` 脉冲;左侧色条标节点类型;
  输入顶点(虚线)、输出徽标、`START`/`END` 胶囊(LangGraph 视图)。
- **SVG pan/zoom**:鼠标滚轮缩放(以光标为中心)、拖拽平移、缩放控制按钮(+/-/fit to view)。
- **进度条 + 耗时计时**:镜像 Wolfram 的"Computing nodes / Elapsed time"。
- **节点详情**:点击看状态/依赖/耗时/token 用量/输出预览/错误 + 复制按钮。
- **LangGraph Mermaid 面板**:运行层视图下显示官方 mermaid 文本 + 复制。
- **事件日志 + Input + ▶ Run**:填 JSON 输入,一键触发,节点逐个亮起。

### 交互优化
- **SSE 自动重连**:指数退避(1s→30s max)、重连状态指示(blink 动画)。
- **运行状态绑定**:Run 按钮与实际 `run.status` 同步,执行中禁用并显示 "⏳ Running"。
- **事件日志上限**:最多 200 条,超出自动移除最旧条目。
- **fetchFullOutput 竞态修复**:序列号计数器确保只有最新请求更新 detail。
- **边标签自适应**:通过 `getComputedTextLength()` 自动宽度,居中于贝塞尔曲线中点。
- **历史分页**:每次显示 10 条,"Show more" 按钮加载更多。
- **Timeline 扩展**:从 10 条增加到 50 条,可滚动。
- **JSON 实时校验**:防抖输入、红/绿边框 + 错误消息。
- **Summary tooltips**:完整文本 `title` 属性,截断时显示 "scroll for more" 指示器。
- **键盘快捷键**:`Ctrl+Enter` 运行、`Esc` 取消选择节点。
- **亮暗主题**:header 中的切换按钮,localStorage 持久化。
- **移动端响应式**:640px 断点,堆叠 summary,隐藏缩放控制。
- **加载状态**:notebook 切换时 canvas 上的 spinner overlay + toast 通知。

## 用法

```bash
llmgraph serve examples/renga.json --backend claude-cli --open
#  → http://127.0.0.1:8765/  ,点 ▶ Run,看 haiku→complete 逐节点亮起
llmgraph serve examples/wolfram-docs/output_nodes.json -i Arg1=1 -i Arg2=2   # 确定性图,免 LLM
```

## 已验证(离线,免 key/网络)

- `monitor.py` 4 个单测:节点状态全覆盖(done/canceled/skipped/error)、覆盖跳过、事件流订阅。
- `server.py` HTTP 单测 + 实跑 SSE:`run_start → node(running/done)×N → run_end` 事件流正确。
- 不挂 monitor 时回归全绿(引擎无侵入)。

## 已基于本事件流实现

- **异步提交 `LLMGraphSubmit`** —— `submit.py` 把 monitor 事件翻译成 HandlerFunctions 事件,
  返回 `Task`。见 [`07-llmgraphsubmit.md`](07-llmgraphsubmit.md)。
- **流式 LLM token**(`claude-cli`):`astream()` → monitor `node_stream` 事件 → SSE → 前端实时显示。
- **token 用量聚合 + 成本估算**(`MODEL_PRICING`,前端 summary bar)。

## 后续

- **多并发运行**:当前同一图实例一次一跑(借 monitor 槽位);并发需各自图实例。
- LangChain backend(anthropic/openai)的流式路径与 monitor 同用时签名待统一(现仅 `claude-cli`)。
