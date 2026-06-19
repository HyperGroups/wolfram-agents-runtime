# 双引擎并行与 Parity(互相验证)

> 状态:设计稿 + 已实现 MVP。最后更新:2026-06-19。

## 原则

**同一张图,默认同时在两个引擎上跑,互为验证:**

- **瘦引擎**:我们的 LangGraph runtime(产品形态,可独立分发、免授权)。
- **WolframEngine 引擎**:Wolfram 原生 `LLMGraph`(参考实现 / oracle)。

每加一个需求,就在两边同步实现并跑 parity:确认迁移忠实、捕捉分歧、迭代整个系统。Wolfram 原生是"规格基准",瘦引擎必须对齐(在无损子集上)。**两边功能都要完备**——某特性若只有一侧支持,parity 报"特性缺口"。

可配置:
- `--engines both|thin|wolfram`(默认 both;生产走 thin)。
- 同步 / 异步(both 时是否并行跑两引擎)。
- 后端两边一致(`--backend`),使 LLM 输出可比。

## Parity 的比对分层(关键:LLM 非确定)

LLM 节点逐字比对不可能(同模型两次都不同,跨引擎更不同)。所以:

| 层 | 比对 |
|---|---|
| **结构** | **精确**:节点集、node→node 依赖边、输出节点名 |
| **确定性节点**(代码 / Wolfram 计算) | **精确**:值相等 |
| **LLM 节点输出** | **并列展示,不断言**(默认模式) |

> 默认模式已选定为「结构精确 + LLM 输出并列」。备选(未实现):同后端+temp0 近似匹配;确定性节点精确断言 + LLM 查形状(适合 CI)。

## 实现(MVP)

- `tools/run_native.wls`:把一份 IR 用 **Wolfram 原生 `LLMGraph`** 跑(每个 string-prompt 节点转成 `EvaluationFunction`,渲染槽位后调 `examples/wolfram/llm.wls` 的统一 `ask[]`),导出结构化 JSON(各节点结果 + 节点/边/输出 + backend)。后端由第 4 个参数 → `LLMGRAPH_WL_BACKEND` 控制(默认 llm.wls 自动解析)。
- `tools/parity.py`:同一 IR 在瘦引擎(`LLMGraph` Python API)和 Wolfram 上各跑一遍,**结构精确比对 + LLM 输出并列**,输出 `PARITY: PASS/FAIL`。

```bash
python tools/parity.py examples/renga.json --input '{"Topic":"autumn"}' --backend claude-cli
```

已验证:`renga` 两引擎结构 parity PASS(claude-cli 后端两侧一致)。

## 官方文档示例的 runtime 化 + 双向测试

把 Wolfram **`LLMGraph` 参考页**(从本机 15.0 内核 `LLMGraph.nb` 抽取)的常见示例
逐一转写成本仓库 IR(`examples/wolfram-docs/`),用 `tools/parity_sweep.py` 一次性在
两个引擎上跑、互验。分两档:

| 档 | 示例 | 比对 | 依赖 |
|---|---|---|---|
| **det**(纯 Wolfram-code) | `doubling`(`2*#Argument`)、`output_nodes`(OutputNode1/MiddleNode/OutputNode2 DAG)、`conditioned`(`ConditionalNode`,test 真/假两支) | **每个节点值精确相等**(两侧跑同一份 WL) | 仅本机 WolframEngine,**免 key/免网络** |
| **llm**(含 string 节点) | `whatis`(LLMSubmission 单节点)、`restyle`(LLM→`ToUpperCase`)、`bestpoem`、`renga` | 结构精确 + LLM 输出并列 | 两侧共用一个 LLM 后端 |

```bash
python tools/parity_sweep.py                       # 仅 det 档:本机精确双向 parity
python tools/parity_sweep.py --with-llm            # 含 llm 档(默认 claude-cli)
python tools/parity_sweep.py --only renga
```

**已验证(det 档,本机,免 key)**:`doubling` 节点值 42==42、`output_nodes` 三节点
值全等、`conditioned`(`ConditionalNode`)test=真→`"NodeHasRun"`、test=假→
`Missing[CanceledNode, ConditionalNode]`,**两支都精确相等**,结构全 OK,`PARITY: PASS`。
静态结构另在 `tests/test_wolfram_docs_examples.py` 钉死(免内核/免 LLM,进 CI)。

**暂不可移植(运行时特性缺口,已显式记录于 `examples/wolfram-docs/README.md`)**:
`ListableLLMFunction` map(`parallel`/`summarize`)、`$Failed` 传播语义(含"被取消节点的
下游"——native 会挂起)。`ConditionalNode` 已支持。

## 已知坑(实测)

- Wolfram 的 `URLRead` 走 schannel 到 dashscope 偶发 SSL 握手失败(Python 的 TLS 栈正常)→ parity 默认用 `claude-cli`(`RunProcess` 调本机 CLI,无网络 TLS)最稳。`llm.wls` 的 HTTP 后端已加重试 + 非 BMP 字符清洗(Wolfram RawJSON 对 emoji 等 >U+FFFF 字符脆弱)。
- 跨进程文本经 `RunProcess`→Wolfram→JSON→Python 偶有 em-dash 等字符 mojibake;仅影响 LLM 节点的展示(不参与断言)。

## 与其它文档

- 架构分层 → [`01-architecture.md`](01-architecture.md)
- 迁移主线 → [`../drafts/migration-and-transpilers.md`](../drafts/migration-and-transpilers.md)
