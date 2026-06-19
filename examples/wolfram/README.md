# Wolfram ↔ Runtime 配对示例

演示主线:**同一张 LLMGraph,在 Wolfram 里跑(claude code 后端) → 翻译成 LangGraph 版 → 我们的 runtime 跑。**
两边都用 **Claude Code 的账号登录**当 LLM 后端,都不需要 Anthropic API key。

## 配对:`renga`

| | Wolfram 版 | Runtime 版(LangGraph) |
|---|---|---|
| 文件 | [`renga.wls`](renga.wls) | [`../renga.json`](../renga.json) |
| 引擎 | Wolfram `LLMGraph`(内核调度) | LangGraph(我们的 runtime) |
| LLM 后端 | `RunProcess` → `claude -p` | `claude-cli` 后端(同样 `claude -p`) |

### 翻译映射(Wolfram LLMGraph → 我们的 JSON IR)

```
node "haiku"    Input {Topic}  prompt "...about <Topic>."     ->  "haiku":    "generate a haiku about `Topic`."
node "complete" Input {haiku}  prompt "...hokku <haiku>..."   ->  "complete": "add an extra stanza to the hokku `haiku` to make it a renga."
graph input  <|"Topic"->...|>                                 ->  --input '{"Topic":"spring"}'
output node  "complete" (sink)                                ->  "output": ["complete"]
```

要点:Wolfram 侧用 `EvaluationFunction`(节点函数收到一个按 `Input` 名键控的关联,用 `a["Topic"]` 取值)把 prompt 拼出来再调 claude;翻译到我们的 IR 后,这些就是**原生的 string prompt 节点 + `` `slot` `` 依赖**。

## 运行

```bash
# 1) Wolfram 版(需本机 Wolfram + 已登录的 claude CLI)
wolframscript -file examples/wolfram/renga.wls

# 2) Runtime 版(LangGraph;同一张图)
llmgraph run examples/renga.json -i Topic=spring --backend claude-cli
```

两者产出对等(都生成 hokku + 接续 7-7 的 renga)。

## 自动转译流水线(整条链路闭环)

不用手抄 JSON。把 Wolfram 侧的 `LLMGraph` spec 自动转成 IR,再交给 runtime:

```
renga_native.wls   (spec = <|"name" -> "prompt with `slots`", ...|>  = 知识)
   │  tools/wlg2json.wls   ← 转译器,免 LLM key(构图是惰性的)
   ▼
renga.generated.json   (我们的 IR;与手写 renga.json 逐字一致)
   │  llmgraph run --backend claude-cli
   ▼
renga 输出
```

```bash
# 转译:Wolfram LLMGraph spec -> 我们的 JSON IR
wolframscript -file tools/wlg2json.wls examples/wolfram/renga_native.wls examples/wolfram/renga.generated.json

# 执行生成的 IR
llmgraph run examples/wolfram/renga.generated.json -i Topic=autumn --backend claude-cli
```

- [`renga_native.wls`](renga_native.wls):规范的"知识"形态(原生 string-LLM spec,反引号槽位)。
- [`../../tools/wlg2json.wls`](../../tools/wlg2json.wls):转译器。覆盖**无损子集**(string-LLM 节点);非字符串节点(`EvaluationFunction` 等)不会被静默丢弃,而是写成 `{"todo":...}` 并报告。
- `*.generated.json` 是可重建产物,已加入 `.gitignore`。

## Wolfram 侧文件一览

| 文件 | 作用 |
|---|---|
| [`llm.wls`](llm.wls) | ★ **cloud-optional 统一 LLM 接入** `ask[]`:默认 cloud-free(deepseek/qwen/claude),`LLMGRAPH_WL_BACKEND=cloud` 才用 Wolfram AI Access。同一份图有/无云都跑。 |
| [`deepseek_config.wls`](deepseek_config.wls) | **原生模式 B 示例**:DeepSeek 是 Wolfram 注册服务,设 `DEEPSEEK_API_KEY` 即可原生 `LLMSynthesize`/`LLMGraph`,直连、免云。 |
| [`renga.wls`](renga.wls) | 真实 Wolfram `LLMGraph`(claude 后端,`RunProcess`)。 |
| [`renga_native.wls`](renga_native.wls) | 规范 spec(字符串 prompt),供转译器。 |

### cloud-optional 接入(推荐写法)

```wolfram
Get["examples/wolfram/llm.wls"];
g = LLMGraph[<|"slogan" -> <|"Input" -> {"Topic"},
      "EvaluationFunction" -> Function[s, ask["4-word slogan about " <> s["Topic"]]]|>|>];
g[<|"Topic" -> "spring"|>]
```

后端解析(`LLMGRAPH_WL_BACKEND` 可强制):auto = `deepseek key → qwen key → claude CLI → cloud LLM Kit`。**默认绕开 Wolfram Cloud,即使云可用**;详见 [`../../docs/design/03-wolfram-integration.md`](../../docs/design/03-wolfram-integration.md)。

## 双引擎 parity(互相验证)

同一份 IR 在瘦引擎(LangGraph)和 Wolfram 原生 LLMGraph 上各跑一遍,**结构精确比对 + LLM 输出并列**:

```bash
python tools/parity.py examples/renga.json --input '{"Topic":"autumn"}' --backend claude-cli
# → PARITY: PASS (structure matches)
```

见 [`../../docs/design/05-dual-engine-parity.md`](../../docs/design/05-dual-engine-parity.md)。

## 备注

- Wolfram 节点用 `EvaluationFunction` + 直连 provider / 本机 CLI(经 `llm.wls` 的 `ask[]`),**不依赖 Wolfram 的 LLM Kit / 云账号**;唯一保留的是 WolframEngine 引擎许可本身。LLM 鉴权三模式见 [`../../docs/design/03-wolfram-integration.md`](../../docs/design/03-wolfram-integration.md)。
- 这对例子也是"无损迁移层"(见 [`../../docs/drafts/migration-and-transpilers.md`](../../docs/drafts/migration-and-transpilers.md))的活样本:结构 + prompt 可确定性地 1:1 转换。
