# Manju Provider API Evidence

更新日期：2026-06-10

本目录只保存人工整理后的接口证据文档，不保存官方页面原始 HTML，也不长期保存第三方源码克隆。官方供应商以官方文档 URL 为准；自定义网关以 GitHub 官方仓库、commit 和源码路径为准。

## 本地文件

- `api-interface-matrix.md`：各供应商/网关的调用方式、解析方式、结构化输出能力和 Manju 当前风险。
- `call-paths-and-custom-providers.md`：按 Manju 实际调用面拆分官方供应商、自定义供应商和 `claude-agent-sdk` 对话链，并列出常见自定义/聚合网关。
- `verification-log.md`：两轮核对记录、来源 URL、源码 commit 和未解决缺口。

## 证据等级

- `可落地`：官方文档或自定义网关源码能明确证明请求字段和响应解析字段。
- `条件可落地`：核心接口明确，但结构化输出或流式事件存在版本/部署差异；代码必须做 capability 配置或探测。
- `暂缓落地`：只看到导航、搜索摘要或现有代码假设，缺少足够的官方正文/源码证据。

## 当前故障结论

`custom-1/gpt-5.5` 报错：

```text
结构化输出无效：模型返回 JSON 但不符合 schema: title: Field required; scenes: Field required
```

不是后处理 jq/Python 摘要解析造成的。直接原因是生成阶段拿到了“合法 JSON”，但它没有满足 `DramaEpisodeScript` 的 schema。OpenAI 官方文档明确区分 JSON mode 和 Structured Outputs：JSON mode 只保证 JSON 语法；只有 Structured Outputs 才承诺按 JSON Schema 约束输出。

因此修复方向不能是“JSON 解析再宽松一点”，而是：

1. 对需要 `DramaEpisodeScript` 这类强 schema 的任务，只走已证实支持 JSON Schema 结构化输出的接口。
2. 不允许从 `json_schema` 静默降级到 `json_object` 后还宣称是 strict schema。
3. 自定义供应商不能只凭模型名推断 `/v1/responses` 或 `text.format.json_schema` 可用，必须由 endpoint 配置、网关源码证据或在线 capability probe 决定。

## 更新原则

新增或修改供应商适配前，必须完成两轮核对：

1. 第一轮：读取官方文档或 GitHub 源码，记录 URL、commit、接口路径、请求字段、响应字段。
2. 第二轮：反向对照 Manju 当前 backend 实现和同一来源的另一处证据；不一致时标记为 `条件可落地` 或 `暂缓落地`，先不要写生产逻辑。

## 供应商分类口径

Manju 的全局设置里有两类供应商，但实际调用不能只按供应商名称判断：

1. 官方供应商：`ProviderRegistry` 中的大供应商，例如 OpenAI、Gemini、DashScope、Vidu、Grok、火山方舟。文本、图片、视频分别走各自 backend。
2. 自定义/聚合供应商：用户填写 `base_url`、`api_key` 后，再为每个模型选择 endpoint。真正决定请求和解析的是 `EndpointRegistry`，不是“NewAPI / sub2api / OpenRouter / LiteLLM”这类品牌名。
3. `claude-agent-sdk` 对话链：独立读取 Anthropic 兼容环境变量，走 Messages API 形态；它不是文本/图片/视频生成 backend。Agent 需要图片或视频时，应调用 Manju 暴露给 agent 的工具，再由工具转到对应生成 backend。

常见自定义/聚合供应商除了 sub2api、NewAPI，还包括 One API、LiteLLM Proxy、OpenRouter、AI/ML API、Ollama、LM Studio、LocalAI、vLLM。CometAPI、APIMart、getimg.ai 等只在现有代码注释或零散资料中出现，未完成官方文档逐项核对前，不应把它们当成可落地协议。
