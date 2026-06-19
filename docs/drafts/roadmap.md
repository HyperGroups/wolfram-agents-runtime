# 路线图(Roadmap)

> 状态:草稿。最后更新:2026-06-19。
> **现状/已验证**已移至权威快照 [`../STATUS.md`](../STATUS.md);本文件只列**未来计划**。

## 近期完成(2026-06-19)

### 前端全面优化
- **SVG pan/zoom**:鼠标滚轮缩放(以光标为中心)、拖拽平移、缩放控制按钮(+/-/fit to view)
- **SSE 自动重连**:指数退避(1s→30s max)、重连状态指示(blink 动画)
- **运行状态绑定**:Run 按钮与实际 `run.status` 同步,执行中禁用并显示 "⏳ Running"
- **事件日志上限**:最多 200 条,超出自动移除最旧条目
- **fetchFullOutput 竞态修复**:序列号计数器确保只有最新请求更新 detail
- **边标签自适应**:通过 `getComputedTextLength()` 自动宽度,居中于贝塞尔曲线中点
- **历史分页**:每次显示 10 条,"Show more" 按钮加载更多
- **Timeline 扩展**:从 10 条增加到 50 条,可滚动
- **JSON 实时校验**:防抖输入、红/绿边框 + 错误消息
- **Summary tooltips**:完整文本 `title` 属性,截断时显示 "scroll for more" 指示器
- **键盘快捷键**:`Ctrl+Enter` 运行、`Esc` 取消选择节点
- **节点详情复制**:输出预览旁的复制按钮
- **亮暗主题**:header 中的切换按钮,localStorage 持久化
- **移动端响应式**:640px 断点,堆叠 summary,隐藏缩放控制
- **加载状态**:notebook 切换时 canvas 上的 spinner overlay

### 后端自动检测(Auto/Manual 模式)
- **Auto 模式(默认)**:`--backend auto` 或不指定 → 自动检测可用凭据
  - 优先级:API keys(anthropic → qwen/openai/deepseek)→ CLI tools(claude-cli)
  - 如果指定的 backend 没有凭据 → 自动切换到可用的,并打印 warning
- **Manual 模式**:`--backend-strict` → 严格使用指定的 backend,无凭据则报错
- **新增函数**:`detect_available_backend()`、`validate_backend()`、`resolve_backend()`

### 错误处理改进
- `server.py` worker 现在正确调用 `monitor.end_run(status="error")` 和 `node_error()`
- 错误事件会推送到前端,不再静默吞掉

## 下一步(按优先级)

### P0 - 核心功能 ✅ 已完成
1. **`ListableLLMFunction`(map / 扇出)**: ✅ 已实现。`{"listable_llm": "...", "input": [...]}` 并行 map 过列表输入。解锁官方 `parallel`、`summarize` 示例。
2. **失败 / 取消传播语义**: ✅ 已实现。`FailedNode` 和 `CanceledNode` 自动传播到下游节点;wolfram 节点 `$Failed` 返回 `FailedNode` 而非抛错;独立分支不受影响。
3. **parity harness 健壮性**: ✅ 已实现。`--timeout` 参数(默认 120s)防止孤儿内核锁 license;`-noprompt` 守护。

### P1 - 体验增强 ✅ 大部分完成
4. **流式 LLM token**: ✅ 已实现。后端 `astream()` 支持,monitor 发射 `node_stream` 事件,前端实时显示生成过程。
5. **成本估算**: ✅ 已实现。`MODEL_PRICING` 定价表,图级 token 聚合,前端 summary bar 显示成本。
6. **多运行对比**: ✅ 已实现。前端支持选择多个历史运行,侧边对比显示每个节点的输出、状态、耗时、模型。后端 `/api/notebooks/<id>/runs/compare` 端点。
7. **图编辑器**: 前端可视化编辑节点、连线,实时预览。(待实现)
8. **检查点 / 可恢复**: 长时间运行的图支持断点续跑。(待实现)

### P2 - 扩展能力
9. **服务接口**:HTTP / `ExternalEvaluate` 入口,供 Wolfram 反向调用本运行时。
10. **转译器增强**:从 `LLMGraph[<|...|>]` 对象直接抽取(而非要求源暴露 `spec`);支持更多节点
    类型(association nodespec、显式 `Input`、`wolfram` 计算节点、条件节点)。
    - 当前:从源文件的 `spec` 关联抽取 string-LLM 节点(无损子集)。
    - 备选:免内核**文本解析** .nb/.wls(彻底脱离 Engine)。
11. **保真度档位**(`faithful`/`enhance`/`simplify`)+ 偏离标注(见迁移草案,暂不展开)。
12. **`wolframclient` 常驻内核**(可选,仅当需要低延迟/高吞吐;当前子进程对分钟/小时级任务足够)。

### P3 - 高级特性
13. **环路 / 状态机**:支持循环依赖、条件分支、状态机模式。
14. **AI 辅助迁移助手**:自动分析 Wolfram notebook,生成迁移建议 + IR 草案。
15. **多提供方后端扩展**:Gemini、Mistral、本地模型(Ollama)等。
16. **分布式执行**:跨机器调度节点,支持大规模图。

## 延后

- `"LLMGraph"` 带结果属性的更多形态。
- human-in-the-loop 交互节点。
- 图版本管理 / diff / merge。

## 参考

- **当前进展 → [`../STATUS.md`](../STATUS.md)**
- 定位 → [`../design/00-overview.md`](../design/00-overview.md)
- 双引擎 parity → [`../design/05-dual-engine-parity.md`](../design/05-dual-engine-parity.md)
- 迁移主线 → [`migration-and-transpilers.md`](migration-and-transpilers.md)
- 运行时监控 → [`../design/06-runtime-monitor.md`](../design/06-runtime-monitor.md)
