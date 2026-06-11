# API Interface Matrix

更新日期：2026-06-10

## 文本生成与结构化输出

| 供应商/网关 | 接口与请求 | 响应解析 | 流式解析 | 证据等级 | Manju 处理结论 |
| --- | --- | --- | --- | --- | --- |
| OpenAI Responses | `POST /v1/responses`；输入用 `input`；schema 用 `text.format = {"type":"json_schema","name":...,"strict":true,"schema":...}`。 | 优先读顶层 `output_text`；否则扫描 `output[].content[].text`。 | 追加 `response.output_text.delta`；以 `response.completed` 结束；错误/截断需处理 `response.failed`、`response.incomplete`。 | 可落地 | 官方 OpenAI 可作为 strict schema 路径。失败时不应自动降级到 `json_object` 并继续当作 strict。 |
| OpenAI Chat Completions | `POST /v1/chat/completions`；messages；schema 用 `response_format = {"type":"json_schema","json_schema":{"name":...,"strict":true,"schema":...}}`。 | `choices[0].message.content`。 | `choices[].delta.content`。 | 可落地 | 适合作为支持 Chat JSON Schema 的供应商路径。 |
| Google Gemini | REST 文档使用 `generationConfig.responseMimeType = "application/json"` 加 `responseSchema`/JSON Schema；Manju 通过 google-genai SDK 的 `response_mime_type`、`response_schema`、`response_json_schema` 调用。 | SDK 通常通过 response text/candidates 取 JSON 字符串后再校验。 | 需按 SDK stream chunk text/candidate 追加。 | 可落地，带 schema 子集限制 | 官方说明支持一部分 JSON Schema。实现必须保留本地 schema 校验，因为不是完整 JSON Schema 方言。 |
| DashScope OpenAI-compatible Qwen | `POST https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions`；OpenAI-compatible Chat；结构化文档明确的是 `response_format = {"type":"json_object"}`。 | 非流式读 `choices[].message.content`，usage 在 `usage`。 | 流式读 `choices[].delta.content`；如启用 `include_usage`，最后 chunk 可能只带 usage。 | 条件可落地 | 当前证据只证明 JSON object，不证明 JSON Schema strict。不能用于必须满足 `DramaEpisodeScript` schema 的 strict 路径，除非后续找到官方 json_schema 证据。 |
| xAI/Grok Structured Outputs | xAI 官方文档说明可用 `response_format.type = "json_schema"` 和 `response_format.json_schema`；Manju 当前 Grok backend 通过 `xai_sdk` 的 `chat.parse(PydanticModel)` 路径调用。 | Manju 取 SDK 解析后的 Pydantic 对象并 `model_dump_json()`，最终仍走本地 schema 校验。 | 当前 Manju Grok backend 不是 SSE 聚合解析路径，流式能力不在本轮证据内。 | 可落地，带 schema 子集限制 | 可作为官方 strict 候选之一；但要按 xAI JSON Schema 子集限制和 SDK 行为校验，不应泛化给 OpenAI-compatible 网关。 |
| Volcengine/BytePlus ModelArk | 官方页面能确认存在 Chat API、Responses API、结构化输出 beta 页面；搜索摘要显示 Chat `response_format.json_schema` 和 Responses 结构化输出字段。 | 需以官方正文或可复制示例为准。 | 需以官方正文或可复制示例为准。 | 暂缓落地 | 现有 Manju Ark 代码按 Chat `response_format.json_schema` 调用，但当前证据不足以扩展/重写。需要抓取可读官方正文或官方示例后再落地。 |
| NewAPI Chat | `POST /v1/chat/completions`；官方 docs 列出 `model`、`messages`、`stream`、`response_format`。 | `choices[].message.content`，usage 在 `usage`。 | OpenAI Chat chunk 形态。 | 可落地 | 对 NewAPI 网关，Chat 路径和解析可以按 OpenAI-compatible Chat 实现，但 schema 能力仍取决于后端 channel。 |
| NewAPI Responses | `POST /v1/responses`；官方 docs 列出 `model`、`input`、`instructions`、`max_output_tokens`、`stream`、`tools`、`reasoning` 等；源码 DTO 支持 `Text` 字段。 | 官方示例含 `output[].content[].text`；源码也按 Responses event/response 处理。 | 源码处理 `response.output_text.delta`，终态事件累积 usage。 | 条件可落地 | 源码支持 Responses 路由；但 docs 对 `text.format.json_schema` 展开不充分。Manju 不能只凭模型名给 NewAPI 强走 Responses strict，需要 capability 配置或 probe。 |
| sub2api Chat/Responses Gateway | 入站支持 `/v1/chat/completions`、`/v1/responses`；源码会按账号能力把 Chat 转 Responses，或对不支持 Responses 的上游直转 Chat。 | Responses 健康检查优先 `output_text`，再扫 `output[].content[].text`；Chat 读 `choices`。 | Responses 事件需要 `response.output_text.delta` 和合法终态；源码专门合成 `response.failed` 避免 silent EOF。 | 条件可落地 | sub2api 是动态网关，不是固定 OpenAI clone。Manju 必须按用户配置或探测决定 endpoint；不得因 `gpt-5.5` 名称自动认定 `/v1/responses` strict 可用。源码 `ResponsesRequest.Text` 目前只看到 `verbosity`，未证明 `text.format.json_schema` 保留。 |
| One API | GitHub README 说明使用方式与 OpenAI API 一致，OpenAI SDK base URL 示例为 `https://<HOST>:<PORT>/v1`。 | 通常按 OpenAI-compatible Chat 读 `choices`；其他能力取决于 One API 版本和下游渠道。 | 未完成 Responses/stream strict 源码核对。 | 条件可落地 | 先只当 `openai-chat` 候选；不要默认支持 Responses strict、图片或视频。 |
| LiteLLM Proxy | 官方文档说明 proxy 是 OpenAI-compatible gateway；另有 Anthropic `/v1/messages` 统一接口。 | OpenAI-compatible 走 `choices`；Anthropic-compatible 走 Messages blocks。 | LiteLLM `/v1/messages` 文档明确支持 streaming；OpenAI stream 仍按 endpoint。 | 条件可落地 | 文本可做 custom endpoint；agent 可做 Anthropic gateway。strict schema 取决于被路由 provider/model。 |
| OpenRouter | `POST https://openrouter.ai/api/v1/chat/completions`；官方说明 request/response schema 类似 OpenAI Chat，并归一化 `choices`。 | `choices[].message` 或 stream `choices[].delta`。 | 官方 quickstart 说明支持 streaming。 | 条件可落地 | 可作为 `openai-chat`。当前证据未证明可用于 `claude-agent-sdk`，也未证明 Responses strict。 |
| Ollama | 官方 OpenAI compatibility 支持 `/v1/chat/completions`、`/v1/responses`；还提供 Anthropic `/v1/messages`。 | Chat 读 `choices`；Responses 读 `output_text`；Messages 读 Anthropic content blocks。 | 两边均有 streaming 示例或事件说明。 | 条件可落地 | 本地文本/agent 候选。图片 `/v1/images/generations` 是 experimental；不要作为视频后端。 |
| LM Studio | 官方 OpenAI compatibility 支持 OpenAI-compatible endpoints；Anthropic compatibility 支持本地 `/v1/messages`。 | OpenAI-compatible 按 Chat/Responses；Messages 按 Anthropic content blocks。 | 博客说明 `/v1/messages` SSE 事件含 `message_start`、`content_block_delta`、`message_stop`。 | 条件可落地 | 本地文本/agent 候选；tool use、strict schema 取决于本地模型与 LM Studio 版本。 |
| LocalAI | 官方 overview 明确 OpenAI、Anthropic、Open Responses API drop-in；GitHub README 说明 backend 覆盖 LLM、vision、voice、image、video。 | OpenAI-compatible/Anthropic-compatible 分别解析；图片/视频 endpoint 取决于启用 backend。 | integration 文档说明 Anthropic Messages API 支持 streaming 和 non-streaming。 | 条件可落地 | 文本和 agent 是明确候选；图片/视频不能凭 LocalAI 品牌直接接入，必须按具体 backend/model 配置 capability 和 endpoint。 |
| vLLM | 官方 online serving 支持 `/v1/completions`、`/v1/responses`、`/v1/chat/completions` 和 Anthropic `/v1/messages`。 | OpenAI-compatible 或 Anthropic-compatible 各自解析。 | 需要按 vLLM server 支持事件处理。 | 条件可落地 | 适合文本/agent；不是图片/视频生成后端。 |

## 视频与图像生成

| 供应商/网关 | 接口与请求 | 响应/轮询解析 | 证据等级 | Manju 处理结论 |
| --- | --- | --- | --- | --- |
| OpenAI Video | `POST /videos` 创建；`GET /videos/{video_id}` 查询；`GET /videos/{video_id}/content` 下载；请求用 `seconds` 控制长度。官方文档确认 `sora-2` 与 `sora-2-pro` 支持 16 和 20 秒，Batch 示例包含 `seconds:"16"` / `"20"`。 | 状态包含 `queued`、`in_progress`、`completed`、`failed`，并可能返回 progress/error。 | 可落地 | 按官方 video API 解析，不要混用 NewAPI/Kling 的 status 字段；Manju `sora-2*` 默认时长预设应包含 `[4,8,12,16,20]`。 |
| DashScope Wan video | `POST /api/v1/services/aigc/video-generation/video-synthesis` 创建异步任务。 | 创建返回 `task_id`；轮询任务状态，成功后取视频 URL。 | 可落地 | Manju DashScope video 后端应坚持异步 task 模型。 |
| Vidu Text to Video | `POST https://api.vidu.com/ent/v2/text2video`；header `Authorization: Token {api key}`；body 包含 `model`、`prompt`、`duration`、`aspect_ratio`、`resolution`、`callback_url` 等。 | 创建返回 `task_id` 和 `state`；状态有 `created`、`queueing`、`processing`、`success`、`failed`。 | 可落地 | 文生视频 endpoint 已确认。 |
| Vidu Image to Video | `POST https://api.vidu.com/ent/v2/img2video`；body 包含 `model`、`images`、`prompt`、`duration`、`resolution`、`callback_url` 等。 | 创建返回 `task_id` 和 `state`；轮询用 `GET https://api.vidu.com/ent/v2/tasks/{id}/creations`，成功结果在 `creations[].url`、`cover_url`。 | 可落地 | 图生视频 endpoint 和轮询 endpoint 已确认。 |
| OpenAI Image API / Responses image tool | Image API 使用 `/v1/images/generations` 和 `/v1/images/edits`；Responses API 可通过 `image_generation` tool 生成图片。 | Image API 示例读 `data[0].b64_json`；Responses image tool 示例从 `response.output` 中筛 `image_generation_call.result`。 | 不在本轮流式证据范围。 | 可落地 | Manju `openai-images*` 自定义 endpoint 对应 Image API；Responses image tool 是官方能力，但不能和 `openai-images` endpoint 混为同一解析。 |
| xAI/Grok Image | xAI 官方 REST 文档确认 `/v1/images/generations` 和 `/v1/images/edits`；示例 base URL 为 `https://api.x.ai/v1`，header 为 Bearer key。 | 响应 `data` 数组，示例含 `url`、`mime_type`、`revised_prompt` 和 usage。 | 不在本轮流式证据范围。 | 可落地 | 对应官方 `grok` image backend；不要用该证据证明其他自定义网关的 image endpoint。 |
| NewAPI OpenAI-compatible Video | `POST /v1/videos` multipart/form-data；字段包括 `model`、`prompt`、`image`、`duration`、`width`、`height`、`fps`、`seed`、`n`。 | 响应含 `id`、`status`、`progress`、`error` 等；内容下载走 OpenAI-compatible video 路径。 | 可落地 | 与 OpenAI Video 形态相近，但必须按 NewAPI docs 处理 multipart 字段。 |
| NewAPI Kling/Jimeng Video | `POST /v1/video/generations` JSON；字段包括 `model`、`prompt`、`duration`、`fps`、`height`、`width`、`image`、`metadata`。 | `GET /v1/video/generations/{task_id}`；状态为 `processing`、`succeeded`、`failed`；成功取 `url`。 | 可落地 | 不要把该接口状态混成 OpenAI `completed`。 |
| AI/ML API `/v2/video/generations` | `POST https://api.aimlapi.com/v2/video/generations` 创建任务；`GET` 同路径并用 `generation_id` 查询。 | 状态枚举为 `queued`、`generating`、`completed`、`error`；完成后响应含 `video` 对象。 | 可落地（仅 AI/ML API） | Manju 的 `v2-video-generations` 只能先按 AI/ML API 证据落地。不能泛化到 xAI/getimg/APIMart/CometAPI。 |
| xAI Video | `POST https://api.x.ai/v1/videos/generations` 创建；`GET /v1/videos/{request_id}` 查询。 | 创建返回 `request_id`；状态包括 `pending`、`done`、`expired`、`failed`；完成后 `video.url`。 | 可落地 | xAI video 不等于 generic `/v2/video/generations`；需要独立 backend 或明确 endpoint 映射。 |

## Claude Agent SDK 对话链

| 供应商/网关 | Anthropic 兼容入口 | 认证变量 | 证据等级 | Manju 处理结论 |
| --- | --- | --- | --- | --- |
| Anthropic Official | `https://api.anthropic.com` | `ANTHROPIC_API_KEY` | 可落地 | `anthropic-official` preset 匹配。 |
| DeepSeek | `https://api.deepseek.com/anthropic` | `ANTHROPIC_AUTH_TOKEN` | 可落地 | `deepseek` preset 匹配。 |
| Zhipu GLM CN | `https://open.bigmodel.cn/api/anthropic` | `ANTHROPIC_AUTH_TOKEN` | 可落地 | `glm-cn` preset 匹配。 |
| Z.AI GLM Global | `https://api.z.ai/api/anthropic` | `ANTHROPIC_AUTH_TOKEN` | 可落地 | `glm-intl` preset 匹配。 |
| MiniMax CN/Global | `https://api.minimaxi.com/anthropic` / `https://api.minimax.io/anthropic` | `ANTHROPIC_AUTH_TOKEN` | 可落地 | 两个 MiniMax preset 匹配。 |
| Kimi/Moonshot | `https://api.moonshot.ai/anthropic` | `ANTHROPIC_AUTH_TOKEN` | 可落地 | Manju 当前 `kimi` preset 与官方资料不匹配，需修正或另建官方 preset。 |
| LiteLLM Proxy | 自部署 host 的 Anthropic `/v1/messages` | 取决于 proxy 配置 | 条件可落地 | 可作为 agent gateway，但要让用户配置 base URL/auth mode。 |
| Ollama | `http://localhost:11434` | `ANTHROPIC_AUTH_TOKEN=ollama`（本地可忽略） | 条件可落地 | 本地 agent 候选，模型需支持工具调用。 |
| LM Studio | `http://localhost:1234` | `ANTHROPIC_AUTH_TOKEN=lmstudio` 或本地 token | 条件可落地 | 本地 agent 候选，模型需支持工具调用。 |
| LocalAI | `http://127.0.0.1:8080` 等 | `ANTHROPIC_API_KEY` | 条件可落地 | 私有部署 agent 候选，按 LocalAI 配置。 |
| vLLM | 自部署 host 的 `/v1/messages` | 取决于 server 配置 | 条件可落地 | 文本/agent 候选，不是图片/视频后端。 |

## 对本次 `custom-1/gpt-5.5` 的直接建议

1. `custom-1` 如果实际是 NewAPI/sub2api，先把 endpoint 类型从“按模型名推断”改成“用户配置/探测结果优先”。
2. 结构化剧本生成如果要求 `DramaEpisodeScript`，只能选择 `supports_json_schema = true` 的 endpoint。
3. 如果 `json_schema` 请求被拒绝，不要 fallback 到 `json_object` 后继续执行；应该换已确认 strict 的 endpoint，或返回明确错误：该供应商只支持 JSON mode，不能保证剧本 schema。
4. 对只支持 JSON object 的供应商，可以另做“非 strict + 本地校验 + 纠错重试”模式，但不能混入 strict 生成链路。
