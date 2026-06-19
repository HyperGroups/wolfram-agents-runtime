# Wolfram 集成与交互通道

> 状态:设计稿 + 本机实测。最后更新:2026-06-19。
> 实测环境:Wolfram 15.0.0 (Windows, 2026-05-19),`$InstallationDirectory = C:\Program Files\Wolfram Research\Wolfram\15.0`。
> 约定(沿用 AGENTS.md):`[✓]` = 已在内核确认存在;标注"推断"= 由符号缺失/上下文推断,未直接验证。

## 三个接触面

```
              ┌─────────────────────────────────────┐
   ①兼容      │   我们的 Runtime (LangGraph 底座)     │   ③被调用
  Wolfram ───▶│   = LLMGraph 语义的超集              │◀─── Wolfram
  LLMGraph    │                                      │   (当工具/服务)
  的模型      │   ②节点内部可回调 Wolfram 内核计算    │
              └───────────────┬─────────────────────┘
                              ▼ 调 Wolfram 算
                        wolframscript / 内核
```

- **① 兼容**:接受 LLMGraph 模型,见 [`02-llmgraph-ir.md`](02-llmgraph-ir.md) 的兼容子集。
- **② 计算节点**:某些节点回调 Wolfram(计算层,需 Engine 许可)。
- **③ 被调用**:Wolfram 把重活外包给我们这个更强的 runtime。

## 数据交换格式

| 格式 | 确认 | 用途 |
|---|---|---|
| **WXF**(`BinarySerialize`/`BinaryDeserialize`/`ExportByteArray["...","WXF"]`) | `[✓]` | 二进制、保真 Wolfram 表达式;官方 Python 库有纯 Python 编解码 |
| **JSON**(`"RawJSON"`/`"ExpressionJSON"` 格式,`ImportString`/`ExportString`) | `[✓]` | **我们 IR 的锚点** |
| `ByteArray` | `[✓]` | 原始字节 |

## 出站:Wolfram → 外部(= ③ Wolfram 调我们,按集成紧密度)

| 通道 | 确认 | 说明 |
|---|---|---|
| `ExternalEvaluate["Python",…]` / `StartExternalSession` | `[✓]` | **本机已注册 Python evaluator,指向我们这个 Python 3.12**(`...\Python312\python.exe`,走 ZMQ,依赖 numpy/zmq/pyarrow)。可**进程级直接 import 我们的库**,无网络无 CLI。最紧。 |
| `RunProcess` / `StartProcess`(+`ProcessObject`/`ReadString`/`WriteLine`) | `[✓]` | 调 `llmgraph` CLI;`StartProcess` 可常驻+流式。零基建。 |
| `URLRead`/`URLExecute`/`URLSubmit`/`HTTPRequest` | `[✓]` | 调我们的 HTTP 服务。跨机通用。 |
| `SocketConnect`/`SocketListen` + `SocketWriteMessage`/`SocketReadMessage`/`SocketWaitAll` | `[✓]` | TCP/ZMQ,双向、流式、低层。 |
| `LinkLaunch`/`LinkConnect`/`LinkWrite`/`LinkRead`(**WSTP**) | `[✓]` | 符号级原生链路,直接传 Wolfram 表达式。 |
| `ExternalFunction` | `[✓]` | 把外部函数包成 Wolfram 函数(底层即 ExternalEvaluate)。 |
| ~~MCP 客户端~~ | **✗(推断)** | 只见服务端符号(下表),**未见"调用外部 MCP 服务器"的客户端符号** → 本机"Wolfram 当 MCP client 调我们"不通。 |

## 入站:外部 → Wolfram(= ② 我们的计算节点)

| 通道 | 确认 | 说明 |
|---|---|---|
| `wolframscript -code/-file`(子进程) | `[✓]` | 已用同套路调 `claude`。**需 Engine 许可。** |
| 官方 `wolframclient`(Python)`WolframLanguageSession` / 异步 pool | 未装(`pip install wolframclient`) | 常驻内核 + WXF 交换,比子进程干净。**Python 侧调 Wolfram 的正路。** |
| WSTP 直连 | `[✓]` | 底层。 |
| **Wolfram 当 MCP server,我们/agent 当 client** | `[✓]` | Wolfram 强项方向;`$DefaultMCPTools` 18 个现成工具(语义 RAG、笔记本读写、paclet 开发等)。 |

## Wolfram 当服务端被调(它最擅长的方向)

`[✓]` 全部确认:

- `APIFunction` + `CloudDeploy` / `CloudPublish`(云 HTTP API)
- `URLDispatcher`(本地/自建 HTTP 路由)
- `StartMCPServer` / `CreateMCPServer` / `InstallMCPServer` / `MCPServerObject`(MCP 服务,被 Claude 等客户端调)
- `SocketListen`(自建 socket 服务)
- `ChannelListen` / `ChannelSend` / `ChannelObject` / `CreateChannel`(pub/sub 通道)

## MCP 现状(实测)

`Names["*MCP*"]` =
`{CreateMCPServer, DetectedMCPClients, InstallMCPServer, MCPServerObject, MCPServerObjectQ, MCPServerObjects, StartMCPServer, UninstallMCPServer, $DefaultMCPPrompts, $DefaultMCPServers, $DefaultMCPToolOptions, $DefaultMCPTools, $SupportedMCPClients}`

**全部偏"服务端 / 把 Wolfram 暴露给客户端"。** 没有连接/调用外部 MCP 服务器的客户端符号。
→ 结论:**Wolfram 15 = MCP 服务端**;"Wolfram 调外部 MCP" 这条路本机不可行(推断)。若以后要走 MCP,方向应是 **我们/agent 调 Wolfram 的 MCP server**。

## 推荐(对应三接触面)

- **③ Wolfram 调我们**:首选 `ExternalEvaluate["Python"]`(最紧,本机就绪)或 `RunProcess` → CLI(零基建);跨机用 HTTP。
- **② 我们调 Wolfram**:首选官方 `wolframclient`(常驻内核);快速验证用 `wolframscript` 子进程。
- **MCP**:仅用于"我们/agent 调 Wolfram 的 18 个工具"方向,不用于反向。

> 注意:运行期互操作通道是**可选增强**,不是迁移主线(见 [`../drafts/migration-and-transpilers.md`](../drafts/migration-and-transpilers.md))的前置条件。

## Per-node backend 在 Wolfram 原生侧的映射

IR 的节点级 `backend`/`model`(`{"prompt":..., "backend":"openai", "model":"gpt-4o"}`)在 `run_native.wls` 中映射到 Wolfram 的 `LLMEvaluator -> LLMConfiguration[<|"Model" -> {service, model}|>]`。映射表:

| IR backend | Wolfram service | 鉴权路径 |
|---|---|---|
| `openai` | `"OpenAI"` | 模式 B:直连(需 `OPENAI_API_KEY`) |
| `anthropic` | `"Anthropic"` | 模式 B:直连(需 `ANTHROPIC_API_KEY`) |
| `deepseek` | `"DeepSeek"` | 模式 B:直连(需 `DEEPSEEK_API_KEY`) |
| `claude-cli` | — | 无 Wolfram 映射,fallback 到 `ask[]` |
| `qwen` / `qwen-tokenplan` | — | Wolfram 未注册 Qwen,fallback 到 `ask[]` |

无 `backend`/`model` 的节点仍走 `ask[]`(cloud-optional 统一接入层)。

## Cloud-optional 原则 + Wolfram LLM 鉴权三模式

**目标:Wolfram 侧的 LLMGraph 工作默认绕开 Wolfram Cloud;但有 Cloud 时,同一份代码/脚本/NB 也能跑。**

Wolfram 原生 LLM 的鉴权/联网有三条路(源码级实测,见项目记忆 [[wolfram-llm-external-facts]]):
- **A. LLM Kit("Wolfram AI Access")= 默认**:未指定 service 时路由到 Wolfram 自己的代理,需 **Wolfram Cloud 账号 + 订阅/积分 + 连 Wolfram 云**。headless 独立内核不弹登录框,无账号直接失败。这就是"要正版 key/连网"的来源。
- **B. 直连 provider**:指定 `Service->"OpenAI"|"Anthropic"|"DeepSeek"|...`,`ConnectToService` 读 `<SERVICE>_API_KEY` 直连,**不走云**。仅限 Wolfram 已注册服务(Qwen 不在内)。
- **C. 完全绕开**(本项目主用):`EvaluationFunction` + `URLRead`/`RunProcess`,任意 provider / 本机 CLI,**零 Wolfram-LLM 鉴权**。

### 统一接入层:`examples/wolfram/llm.wls`

提供一个 cloud-optional 的 `ask[prompt]`,图节点用 `EvaluationFunction -> Function[s, ask[...]]`,**同一份图在有/无云时都跑**:

- 解析顺序(`LLMGRAPH_WL_BACKEND` 可强制):auto = `deepseek key → qwen key → claude CLI → cloud LLM Kit`。
- 默认 **cloud-free 优先**(即使云可用也绕开);设 `LLMGRAPH_WL_BACKEND=cloud` 才用 Wolfram AI Access。
- 实测:同一张图,auto→qwen(云在但被绕开)与强制 claude(无云)均跑通。

结论:**我们跑 LLMGraph 的 LLM 侧零 Wolfram-Cloud 依赖,且 cloud 在场不冲突、可选用**。唯一不可省的是 WolframEngine 引擎许可本身(用于计算节点),非 LLM Kit。
