# Verification Log

更新日期：2026-06-10

## 第一轮：官方文档与 GitHub 源码

### 官方供应商

- OpenAI Structured Outputs：官方说明 Structured Outputs 会按 JSON Schema 约束模型输出；Chat 使用 `response_format`，Responses 使用 `text.format`；JSON mode 只保证 JSON 语法，不保证 schema。
  - URL: https://developers.openai.com/api/docs/guides/structured-outputs
- OpenAI Streaming：官方 Responses stream 事件包含 `response.output_text.delta`、`response.completed`、`error` 等。
  - URL: https://developers.openai.com/api/docs/guides/streaming-responses
- OpenAI Video：官方 video API 使用创建、查询、下载三段式；查询返回 `queued`、`in_progress`、`completed`、`failed` 等状态。
  - URL: https://developers.openai.com/api/docs/guides/video-generation
- OpenAI Image：官方 image generation 文档确认 Image API 有 generations 和 edits 两类 endpoint；Responses API 可通过 `image_generation` tool 生成图片，Image API 示例读取 `data[0].b64_json`。
  - URL: https://developers.openai.com/api/docs/guides/image-generation
- Google Gemini Structured Output：官方文档说明可在 generation config 中设置 JSON mime type 和 schema，模型输出匹配 schema 的 JSON 字符串，但只支持 JSON Schema 子集。
  - URL: https://ai.google.dev/gemini-api/docs/structured-output
- DashScope OpenAI-compatible：官方文档确认 base URL 和 `/compatible-mode/v1/chat/completions`，非流式 `choices[].message.content`，流式 `choices[].delta.content`，可带 usage chunk。
  - URL: https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope
- DashScope Qwen Structured Output：官方文档当前确认的是 `response_format: {"type":"json_object"}`，并要求 prompt 包含 JSON 关键字；未在该页证明 `json_schema` strict。
  - URL: https://www.alibabacloud.com/help/en/model-studio/qwen-structured-output
- DashScope Wan Text-to-Video：官方文档确认异步任务接口 `/api/v1/services/aigc/video-generation/video-synthesis` 和 task polling 模型。
  - URL: https://www.alibabacloud.com/help/en/model-studio/text-to-video-api-reference
- Vidu Text to Video：官方文档确认 `POST https://api.vidu.com/ent/v2/text2video`，创建返回 `task_id`、`state`。
  - URL: https://platform.vidu.com/docs/text-to-video
- Vidu Image to Video：官方文档确认 `POST https://api.vidu.com/ent/v2/img2video`，创建返回 `task_id`、`state`。
  - URL: https://platform.vidu.com/docs/image-to-video
- Vidu Get Creation：官方文档确认 `GET https://api.vidu.com/ent/v2/tasks/{id}/creations`，成功结果在 `creations[].url` 和 `cover_url`。
  - URL: https://platform.vidu.com/docs/get-generation
- Volcengine/BytePlus ModelArk：官方页面确认存在 Chat API、Responses API、Structured output beta 页面，但当前可抓文本主要是导航和更新时间，正文示例不足。
  - URL: https://www.volcengine.com/docs/82379/1568221?lang=zh
  - URL: https://www.volcengine.com/docs/82379/1958523?lang=zh
  - URL: https://docs.byteplus.com/en/docs/ModelArk/1568221
- xAI/Grok Structured Outputs：官方文档确认 `response_format.type = "json_schema"`、schema 放在 `response_format.json_schema`，并说明支持 JSON Schema 子集。
  - URL: https://docs.x.ai/developers/model-capabilities/text/structured-outputs
- xAI/Grok Image：官方 REST 文档确认 `/v1/images/generations`、`/v1/images/edits`，响应为 `data` 数组，示例包含 `url`、`mime_type`、`revised_prompt`。
  - URL: https://docs.x.ai/developers/rest-api-reference/inference/images
- xAI/Grok Video：官方 REST 文档确认 `/v1/videos/generations` 创建、`/v1/videos/{request_id}` 查询；capability 文档说明状态 `pending`、`done`、`expired`、`failed`，成功返回 `video.url`。
  - URL: https://docs.x.ai/developers/rest-api-reference/inference/videos
  - URL: https://docs.x.ai/developers/model-capabilities/video/generation

### 自定义供应商/网关

- NewAPI docs：官方 docs 确认 `/v1/chat/completions`、`/v1/responses`、`/v1/videos`、`/v1/video/generations` 等接口。
  - Chat docs: https://docs.newapi.pro/en/docs/api/ai-model/chat/openai/createchatcompletion
  - Responses docs: https://docs.newapi.pro/en/docs/api/ai-model/chat/openai/createresponse
  - Video docs: https://docs.newapi.pro/en/docs/api/ai-model/videos/sora/createvideo
  - Kling/Jimeng docs: https://docs.newapi.pro/api/kling-jimeng/
- NewAPI source：GitHub `https://github.com/QuantumNous/new-api`，核对 commit `d2576dd`。源码克隆只用于临时核对，本文档不保留源码快照。
  - `common/endpoint_defaults.go`：默认 endpoint 含 `/v1/chat/completions`、`/v1/responses`。
  - `router/relay-router.go`：路由 Chat 和 Responses relay。
  - `router/video-router.go`：路由 `/v1/video/generations`、`/v1/videos` 及查询/内容接口。
  - `dto/openai_request.go`：`OpenAIResponsesRequest` 含 Responses 请求字段。
  - `relay/channel/openai/relay_responses.go`：流式处理 `response.output_text.delta`。
- sub2api source：GitHub `https://github.com/Wei-Shaw/sub2api`，核对 commit `0acf00c`。源码克隆只用于临时核对，本文档不保留源码快照。
  - `backend/internal/handler/endpoint.go`：入站 endpoint 常量与 upstream endpoint 派生逻辑。
  - `backend/internal/handler/openai_chat_completions.go`：可按账号能力把 Chat 直转 `/v1/chat/completions`。
  - `backend/internal/handler/stream_error_event.go`：Responses 流错误需要发送 `response.failed` 终态事件。
  - `backend/internal/pkg/apicompat/types.go`：`ResponsesRequest` 类型字段；当前 `ResponsesText` 只看到 `verbosity`。
  - `backend/internal/pkg/apicompat/chatcompletions_to_responses.go`：Chat 转 Responses。
  - `backend/internal/pkg/apicompat/responses_to_chatcompletions.go`：Responses 转 Chat 和事件累积。

### 追加核对：常见自定义/聚合网关

- One API source/docs：GitHub README 说明“使用方式与 OpenAI API 一致”，OpenAI SDK base URL 示例为 `https://<HOST>:<PORT>/v1`。
  - URL: https://github.com/songquanpeng/one-api
- LiteLLM Proxy：官方文档说明 proxy 是 OpenAI-compatible gateway；`/v1/messages` 文档说明可用 Anthropic `v1/messages` 格式调用所有支持的 LLM API，并支持 streaming、fallback、load balancing。
  - URL: https://docs.litellm.ai/docs/
  - URL: https://docs.litellm.ai/docs/anthropic_unified/
- OpenRouter：官方 quickstart 使用 `/api/v1/chat/completions`；API reference 说明 request/response schema 与 OpenAI Chat API 类似，并归一化 `choices`。
  - URL: https://openrouter.ai/docs/quickstart
  - URL: https://openrouter.ai/docs/api/reference/overview
- AI/ML API：官方视频模型文档确认 `/v2/video/generations` POST 创建任务，GET 同路径按 `generation_id` 查询；状态包括 `queued`、`generating`、`completed`、`error`。
  - URL: https://docs.aimlapi.com/api-references/video-models/runway/gen4_turbo
- Ollama：官方 OpenAI compatibility 确认 `/v1/chat/completions`、`/v1/responses`、实验性 `/v1/images/generations`；官方 Anthropic compatibility 确认 `/v1/messages` 和 Claude Code 环境变量。
  - URL: https://docs.ollama.com/api/openai-compatibility
  - URL: https://docs.ollama.com/api/anthropic-compatibility
- LM Studio：官方 Anthropic compatibility 文档确认本地 `/v1/messages`；Claude Code 博客确认 `ANTHROPIC_BASE_URL=http://localhost:1234`、`ANTHROPIC_AUTH_TOKEN=lmstudio`，并列出 SSE 事件与 tool use 支持。
  - URL: https://lmstudio.ai/docs/developer/anthropic-compat
  - URL: https://lmstudio.ai/blog/claudecode
- LocalAI：官方 overview 确认 OpenAI、Anthropic、Open Responses API drop-in；integration 文档确认 Claude Code 可用 LocalAI Anthropic Messages API；GitHub README 说明其 backend 覆盖 LLM、vision、voice、image、video，但图片/视频具体 endpoint 仍需按 backend 配置核对。
  - URL: https://localai.io/docs/overview/index.html
  - URL: https://localai.io/integrations/
  - URL: https://github.com/mudler/localai
- vLLM：官方 online serving 文档确认 OpenAI-compatible `/v1/completions`、`/v1/responses`、`/v1/chat/completions`，以及 Anthropic `/v1/messages`。
  - URL: https://docs.vllm.ai/en/latest/serving/online_serving/

### 追加核对：Claude Agent SDK / Claude Code 兼容供应商

- Claude Code 环境变量：官方文档说明 `ANTHROPIC_BASE_URL` 可路由到 proxy/gateway；`ANTHROPIC_API_KEY` 与 `ANTHROPIC_AUTH_TOKEN` 分别是不同认证输入。
  - URL: https://code.claude.com/docs/en/env-vars
- DeepSeek：官方 Claude Code 文档使用 `ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic` 和 `ANTHROPIC_AUTH_TOKEN=<key>`。
  - URL: https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code
- MiniMax：官方 Claude Code 文档使用 `https://api.minimax.io/anthropic` 或 `https://api.minimaxi.com/anthropic`，并设置 `ANTHROPIC_AUTH_TOKEN`。
  - URL: https://platform.minimax.io/docs/token-plan/claude-code
- Zhipu GLM：中国区官方文档使用 `ANTHROPIC_BASE_URL=https://open.bigmodel.cn/api/anthropic` 和 `ANTHROPIC_AUTH_TOKEN`。
  - URL: https://docs.bigmodel.cn/cn/guide/develop/claude
- Z.AI：国际区官方文档使用 `ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic` 和 `ANTHROPIC_AUTH_TOKEN`。
  - URL: https://docs.z.ai/devpack/tool/claude
- Kimi/Moonshot：官方 agent support 文档确认 Claude Code/Cline/RooCode 走 Moonshot/Kimi K2.5；直接 API 示例为 OpenAI-compatible `https://api.moonshot.ai/v1`，Claude Code 资料核对到的 Anthropic-compatible 入口为 `https://api.moonshot.ai/anthropic`、认证为 `ANTHROPIC_AUTH_TOKEN`。同页页眉提示 K2.6 已发布，但当前正文可复制配置仍为 K2.5，不能据此直接把 preset 改为 K2.6。
  - URL: https://platform.kimi.ai/docs/guide/agent-support

## 第二轮：反向对照 Manju 当前实现

- `backend/lib/text_backends/openai.py` 当前 Responses backend 会先尝试 `text.format.json_schema`；如果 schema 请求报错或输出无效，会 fallback 到 `json_object`。
- `backend/lib/text_backends/base.py` 的 `ensure_structured_output()` 会在最终 JSON 不符合 Pydantic schema 时抛出当前错误。
- `backend/lib/script_models.py` 的 `DramaEpisodeScript` 顶层必需字段包含 `title` 和 `scenes`。
- `backend/lib/custom_provider/endpoints.py` 当前会按模型名把部分模型推断到 `openai-responses`，这对官方 OpenAI 可以成立，但对 NewAPI/sub2api 这类自定义网关不够可靠。
- `backend/lib/custom_provider/endpoints.py` 的 endpoint 才是自定义供应商请求/解析的单一真相源；One API、LiteLLM、OpenRouter、Ollama、LM Studio、LocalAI、vLLM 等不能只按品牌名落地，必须映射到 `openai-chat`、`openai-responses`、`gemini-generate` 或 Anthropic Messages。
- `backend/lib/agent_provider_catalog.py` 当前 Kimi preset 使用 `https://api.kimi.com/coding`、默认 `api_key`、模型 `kimi-for-coding`；与本轮 Kimi/Moonshot 官方资料不一致，应修正或保留 legacy 后另建官方 preset。
- `backend/lib/config/service.py` 当前对 `deepseek`、GLM、MiniMax 这类 preset 使用 `auth_env_mode="auth_token"`，与官方 Claude Code 文档一致。
- `backend/lib/text_backends/gemini.py` 当前使用 google-genai SDK 的结构化输出字段，和 Gemini 官方 structured output 文档方向一致，但仍需本地 schema 校验。
- `backend/lib/text_backends/ark.py` 当前使用 Chat `response_format.json_schema`，但 Volcengine 官方正文证据仍不足，暂不应扩展该适配。

## 尚未满足落地条件的点

1. Volcengine/BytePlus ModelArk 的结构化输出正文示例需要用可读官方正文、PDF、官方 OpenAPI schema 或官方 SDK 示例再核对一遍；当前只可标记为暂缓落地。
2. DashScope Qwen 当前官方结构化页只证明 JSON object，不证明 JSON Schema strict；不能直接承接 Manju 剧本 schema。
3. sub2api 的 Responses typed request 暂未证明保留 `text.format.json_schema`；如果要支持 sub2api strict schema，需要在目标版本做实际 probe 或找到新增源码证据。
4. Generic `/v2/video/generations` 不能只以 AI/ML API 证据泛化到所有自定义供应商；xAI 已核对为 `/v1/videos/generations` + `/v1/videos/{request_id}`，形态不同。
5. Xiaomi MiMo、ArcReel 的 Manju preset 仍缺可读官方 Claude Code / Anthropic Messages 文档；暂缓扩展。
6. Kimi preset 与当前官方资料不一致，是下一步实现修复的高优先级候选。
