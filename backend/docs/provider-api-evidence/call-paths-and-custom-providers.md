# Provider Call Paths and Custom Providers

更新日期：2026-06-10

本文件只保留人工整理后的接口结论。所有结论按“请求路径、请求字段、响应字段、Manju 当前映射”记录；不保存官方 HTML，也不长期保存第三方源码克隆。

## Manju 实际调用面

### 1. 官方生成供应商

代码入口：`plugins/manju/backend/lib/config/registry.py` 的 `PROVIDER_REGISTRY`。

当前注册项：

- `gemini-aistudio`
- `gemini-vertex`
- `ark`
- `ark-agent-plan`
- `grok`
- `openai`
- `vidu`
- `dashscope`

这些供应商按 `ModelInfo.media_type` 拆成文本、图片、视频三个 backend。不能因为同属一个供应商，就把文本结构化输出、图片生成、视频异步任务、agent 对话混成同一种协议。

### 2. 自定义/聚合生成供应商

代码入口：`plugins/manju/backend/lib/custom_provider/endpoints.py` 的 `ENDPOINT_REGISTRY`。

当前 endpoint：

| endpoint | media_type | 请求形态 | Manju 处理原则 |
| --- | --- | --- | --- |
| `openai-chat` | text | `/v1/chat/completions` | 读 `choices[].message.content`；stream 读 `choices[].delta.content`。 |
| `openai-responses` | text | `/v1/responses` | 读 `output_text` 或 `output[].content[].text`；stream 读 `response.output_text.delta`。strict schema 不能只凭模型名推断。 |
| `gemini-generate` | text | `/v1beta/models/{model}:generateContent` | 按 Gemini generateContent/SDK 形态解析 candidates/text。 |
| `openai-images` | image | `/v1/images/{generations,edits}` | 由是否传参考图决定 generation/edit；读 `data[].b64_json` 或 URL。 |
| `openai-images-generations` | image | `/v1/images/generations` | 只用于文生图。 |
| `openai-images-edits` | image | `/v1/images/edits` | 只用于图生图/编辑。 |
| `gemini-image` | image | `/v1beta/models/{model}:generateContent` | 使用 Gemini 图像输出 content parts。 |
| `openai-video` | video | `/v1/videos` | 按 OpenAI Sora video create/poll/download；`seconds` 控制长度，`sora-2*` 默认候选时长包含 4/8/12/16/20。 |
| `newapi-video` | video | `/v1/video/generations` | 按 NewAPI Kling/Jimeng 任务状态和 `url` 解析。 |
| `v2-video-generations` | video | `/v2/video/generations` | 目前只对 AI/ML API 有官方证据；不要泛化到所有网关。 |
| `ark-seedance` | video | `/api/v3/contents/generations/tasks` | 火山方舟 Seedance 任务形态，仍需用可读官方正文补强。 |
| `vidu-video` | video | `/ent/v2/img2video` | Vidu v2 任务形态；参考图能力按 Vidu backend。 |
| `dashscope-image` | image | `/api/v1/services/aigc/multimodal-generation/generation` | DashScope Qwen-Image 同步接口。 |
| `dashscope-async-video` | video | `/api/v1/services/aigc/video-generation/video-synthesis` | DashScope Wan/HappyHorse 异步 task。 |

自定义供应商表里的 `discovery_format` 只能辅助默认 endpoint 推断；生产调用必须以用户显式 endpoint 或 capability probe 为准。

### 3. `claude-agent-sdk` 对话链

代码入口：

- `plugins/manju/backend/lib/agent_provider_catalog.py`
- `plugins/manju/backend/lib/config/service.py`
- Agent runtime 中的 `ClaudeAgentOptions.env`

这条链使用 Anthropic 兼容 Messages API。Claude Code 官方环境变量说明里，`ANTHROPIC_API_KEY` 会作为 `X-Api-Key`，`ANTHROPIC_AUTH_TOKEN` 会作为 `Authorization: Bearer ...`，`ANTHROPIC_BASE_URL` 用于切到代理或网关。

这条链只负责 agent 对话、工具调用、streaming blocks。它不直接等同于 Manju 的文本/图片/视频生成 backend。Agent 需要生成图片或视频时，应调用 Manju 的 agent tool，再由 tool 使用全局默认图片/视频 backend。

## 四类调用方式

| 调用类型 | 官方供应商路径 | 自定义/聚合路径 | `claude-agent-sdk` 路径 |
| --- | --- | --- | --- |
| 文本模型 | OpenAI Responses/Chat、Gemini generateContent、DashScope OpenAI-compatible Chat、xAI/Grok Chat、Ark Chat 等。 | `openai-chat`、`openai-responses`、`gemini-generate`。OpenRouter/One API/LiteLLM/Ollama/LM Studio/LocalAI/vLLM 都要按其实际 endpoint 归类。 | 不使用文本生成 backend；走 Anthropic Messages `/v1/messages` 兼容接口。 |
| 结构化剧本 | 只允许已证明支持 JSON Schema strict 或 Gemini schema 子集的路径。 | 不能只凭 `gpt-5.5`、`responses`、`OpenAI compatible` 推断 strict schema；必须配置或探测 `json_schema` 能力。 | Agent 对话输出不是 `DramaEpisodeScript` 的 strict 生成路径；需要剧本时应调用可校验的文本生成工具。 |
| 图片模型 | OpenAI Image API / Responses image tool、Gemini image generateContent、DashScope Qwen-Image、xAI/Grok Images、Vidu image。 | `openai-images*`、`gemini-image`、`dashscope-image`。自定义网关是否支持 edits、base64、URL 返回需逐个确认。 | Agent 通过工具间接调用图片 backend，不直接通过 Messages API 生成图片。 |
| 视频模型 | OpenAI `/v1/videos`、Gemini Veo long-running operation、DashScope async video、Vidu task、xAI `/v1/videos/generations`。 | `openai-video`、`newapi-video`、`v2-video-generations`、`ark-seedance`、`vidu-video`、`dashscope-async-video`。不同网关状态字段不同。 | Agent 通过工具间接调用视频 backend，不直接通过 Messages API 生成视频。 |

## 常见自定义/聚合供应商

下面清单回答“除了 sub2api、NewAPI，还有哪些常用自定义供应商”。“可用于 Manju”不代表所有模型都支持 strict schema、图片、视频或 agent；必须按 endpoint 能力落地。

| 名称 | 类型 | 已核对接口证据 | Manju 建议 |
| --- | --- | --- | --- |
| One API | 自部署 key 管理和分发系统 | GitHub README 说明使用方式与 OpenAI API 一致，OpenAI SDK base URL 示例为 `https://<HOST>:<PORT>/v1`。 | 可作为 `openai-chat` 的候选；是否支持 Responses、图片、视频、JSON Schema strict 需按 One API 版本和下游渠道再核对。 |
| LiteLLM Proxy | 自部署 LLM gateway | 官方文档说明 proxy 是 OpenAI-compatible gateway；另有 `/v1/messages` Anthropic 统一接口，支持 streaming、fallback、load balancing。 | 文本可走 `openai-chat`，agent 可走 Anthropic compatible。strict schema 取决于 LiteLLM 路由后的 provider/model，必须配置或 probe。 |
| OpenRouter | 托管聚合 API | 官方 quickstart 使用 `/api/v1/chat/completions`；API reference 说明响应按 OpenAI Chat schema 归一化，`choices` 固定为数组。 | 作为 `openai-chat` 候选。当前证据未证明可直接供 `claude-agent-sdk` 使用，也未证明 Responses strict。 |
| AI/ML API | 托管多模态聚合 API | 官方视频模型文档说明统一短 URL 为 `https://api.aimlapi.com/v2/video/generations`，POST 创建、GET 用 `generation_id` 查询，状态为 `queued/generating/completed/error`。 | `v2-video-generations` 当前只应明确指向 AI/ML API 这类已核对形态。不要把该协议泛化给 xAI/getimg/APIMart/CometAPI。 |
| Ollama | 本地/云模型服务 | 官方 OpenAI compatibility 支持 `/v1/chat/completions`、`/v1/responses`，实验性 `/v1/images/generations`；Anthropic compatibility 支持 `/v1/messages`，并给出 Claude Code env。 | 文本可用 `openai-chat`/`openai-responses`；agent 可用 Anthropic compatible；图片能力仍是实验性；不作为视频后端。 |
| LM Studio | 本地模型服务 | 官方 OpenAI compatibility 支持 OpenAI 风格接口；Anthropic compatibility 文档给出 `http://localhost:1234/v1/messages`，博客说明 Claude Code 可用 `ANTHROPIC_BASE_URL=http://localhost:1234` 和 `ANTHROPIC_AUTH_TOKEN=lmstudio`。 | 文本和 agent 候选。是否能承接工具流、长上下文和 strict schema，要按本地模型与 LM Studio 版本测试。 |
| LocalAI | 自部署本地/私有模型栈 | 官方 overview 写明 OpenAI、Anthropic、Open Responses API drop-in；integration 文档说明 Claude Code 可指向 LocalAI `/v1/messages`，使用 `ANTHROPIC_BASE_URL` 和 `ANTHROPIC_API_KEY`；GitHub README 说明其 backend 覆盖 LLM、vision、voice、image、video。 | 文本和 agent 可按 OpenAI/Anthropic 兼容路径核对；图片/视频必须再按启用的 LocalAI backend 与实际 endpoint 单独核对。 |
| vLLM | 自部署推理服务器 | 官方 online serving 支持 OpenAI `/v1/completions`、`/v1/responses`、`/v1/chat/completions`，并支持 Anthropic `/v1/messages`。 | 适合文本和 agent；不是图片/视频生成后端。strict schema 和 tool calling 依赖模型与 vLLM 支持。 |

暂缓列入可落地清单：

- CometAPI、APIMart、getimg.ai：现有 Manju `v2_video_generations.py` 注释提到这些名字，但尚未逐个取到官方文档或源码证据。
- ArcReel：Manju agent preset 中存在，但当前未核到官方 Anthropic compatible 资料。
- Xiaomi MiMo：Manju agent preset 中存在，但当前只核到产品页，未核到精确的 Claude Code / Anthropic Messages 配置正文。

## Agent preset 二次核对

| preset | Manju 当前值 | 官方资料核对 | 结论 |
| --- | --- | --- | --- |
| `anthropic-official` | `https://api.anthropic.com`，默认 `api_key` | Claude Code 官方说明 `ANTHROPIC_API_KEY` 走 `X-Api-Key`，`ANTHROPIC_BASE_URL` 可覆盖 endpoint。 | 匹配。 |
| `deepseek` | `https://api.deepseek.com/anthropic`，`auth_token` | DeepSeek 官方 Claude Code 文档使用 `ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic`、`ANTHROPIC_AUTH_TOKEN=<key>`。 | 匹配。 |
| `glm-cn` | `https://open.bigmodel.cn/api/anthropic`，`auth_token` | 智谱官方 Claude Code 文档使用 `ANTHROPIC_AUTH_TOKEN` 和 `ANTHROPIC_BASE_URL=https://open.bigmodel.cn/api/anthropic`。 | 匹配。 |
| `glm-intl` | `https://api.z.ai/api/anthropic`，`auth_token` | Z.AI 官方文档使用 `ANTHROPIC_AUTH_TOKEN` 和 `ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic`。 | 匹配。 |
| `minimax-cn` | `https://api.minimaxi.com/anthropic`，`auth_token` | MiniMax 官方文档说明中国区用 `https://api.minimaxi.com/anthropic`，并设置 `ANTHROPIC_AUTH_TOKEN`。 | 匹配。 |
| `minimax-intl` | `https://api.minimax.io/anthropic`，`auth_token` | MiniMax 官方文档说明国际区用 `https://api.minimax.io/anthropic`，并设置 `ANTHROPIC_AUTH_TOKEN`。 | 匹配。 |
| `kimi` | `https://api.kimi.com/coding`，默认 `api_key`，模型 `kimi-for-coding` | Kimi 官方文档正文使用 `ANTHROPIC_BASE_URL=https://api.moonshot.ai/anthropic`、`ANTHROPIC_AUTH_TOKEN=${YOUR_MOONSHOT_API_KEY}`、模型 `kimi-k2.5`；同页页眉提示 K2.6 已发布，但当前可复制的 Claude Code 配置仍是 K2.5。 | 不匹配，需修正或保留为 legacy 并新增官方 preset；若切 K2.6，要先核对官方 agent 配置示例/模型列表。 |
| `ark-coding-plan` | `https://ark.cn-beijing.volces.com/api/coding`，默认 `api_key` | 火山官方页面当前可抓正文主要是导航；官方域名文章提到 Coding Plan Anthropic protocol base URL 为 `/api/coding`，但需官方文档正文/PDF再次确认认证变量。 | 条件可落地，不能扩展。 |
| `ark-agent-plan` | `https://ark.cn-beijing.volces.com/api/plan`，默认 `api_key` | 同上，官方正文证据不足。 | 暂缓扩展。 |
| `xiaomi-mimo` | `https://api.xiaomimimo.com/anthropic`，默认 `api_key` | 未核到官方 Claude Code / Anthropic Messages 配置正文。 | 暂缓扩展。 |
| `arcreel` | `https://api.arc-reel.com`，默认 `api_key` | 未核到官方 Anthropic compatible 配置正文。 | 暂缓扩展。 |

## 对 `custom-1/gpt-5.5` 的实现约束

1. `custom-1` 的供应商名不能决定协议能力；必须看该模型绑定的 endpoint。
2. 只有 OpenAI 官方、Gemini schema 子集、xAI JSON Schema 子集等已证实 schema 能力的路径，才能承接 `DramaEpisodeScript` strict 生成。
3. NewAPI、sub2api、One API、LiteLLM、OpenRouter、Ollama、LM Studio、LocalAI、vLLM 等“OpenAI compatible”只代表基础请求/响应形态相近，不自动代表 `text.format.json_schema` 或 Chat `response_format.json_schema` 一定可用。
4. 若 `json_schema` 请求失败，不能自动降级成 `json_object` 后继续当作 strict。应返回明确 capability 错误、切换 strict provider，或进入“非 strict + 本地校验 + 修复重试”的独立模式。
