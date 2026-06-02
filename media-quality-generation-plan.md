# Manju 草稿/最终版媒体生成方案

## 结论

当前创建项目里的图片分辨率、视频分辨率是项目级默认值。它们会被角色、场景、道具、分镜和视频生成共同使用，所以不适合直接作为“草稿模式”。

草稿能力应该设计成“按生成用途 + 质量档位”的生成策略，而不是简单把项目默认值改成 1K / 720p。否则角色、场景、道具这些母资产也会被低规格生成，后续所有分镜和视频都会继承低质量参考图。

本方案目标不是单纯决定“使用 PNG 还是 JPEG”，而是建立一套兼顾以下指标的生产链路：

- 角色一致性：脸、发型、服装、体型、道具在多镜头中稳定。
- 分镜准确性：人物位置、镜头构图、场景、道具、动作起点符合剧本。
- 视频质量：动作自然，少变形、少融脸、少闪烁。
- 成本可控：减少失败重试，按镜头重要程度选择模型档位。
- 请求稳定：避免大图、Base64 膨胀和请求体限制导致失败。
- 资产可复用：母版图、分镜图、视频版本可追溯、可回滚。

推荐原则：

```text
母资产高质量
分镜草稿低成本
视频草稿低成本
最终成片统一规格
供应商参数按能力校验
视频输入图按供应商临时优化
视频 prompt 只描述运动和镜头
```

推荐默认值：

```text
角色/场景/道具母资产：2K
分镜草稿：1K
分镜最终版：2K
宫格镜头板：跟随项目图片规格，默认 2K，不使用 1K 草稿
视频草稿：720p / 跟随镜头实际时长
视频最终版：1080p / 正式时长
参考视频草稿：720p / 跟随 unit 实际时长
参考视频最终版：1080p / 正式时长
```

三种视频生成模式的定位必须拆开：

```text
图生视频：单分镜图 -> 单视频；适合最终生产，保留分镜草稿/最终版 + 视频草稿/最终版。
宫格生视频：宫格镜头板 -> 切分单格首帧 -> 批量视频；宫格本身不走低清草稿，直接使用项目图片规格，拆分单格不再单独高清化。
参考生视频：资产参考图 + unit prompt -> 视频；跳过分镜图，使用 reference_video_draft/final 独立策略。
```

## 当前创建项目流程

### 前端创建向导

创建项目入口：

- `plugins/manju/frontend/src/components/pages/CreateProjectModal.tsx`
- `plugins/manju/frontend/src/components/pages/create-project/WizardStep1Basics.tsx`
- `plugins/manju/frontend/src/components/pages/create-project/WizardStep2Models.tsx`
- `plugins/manju/frontend/src/components/shared/ModelConfigSection.tsx`

当前创建项目会收集：

- 项目标题
- 内容模式：旁白 / 剧本
- 画幅：9:16 / 16:9
- 生成模式：分镜 / 九宫格 / 参考视频
- 视频模型
- 文生图模型
- 图生图模型
- 三类文本模型：脚本、概览、风格
- 默认视频时长
- 图片分辨率
- 视频分辨率

`WizardStep2Models` 会读取：

- `API.getSystemConfig()`
- `API.getProviders()`
- `API.listCustomProviders()`

然后根据内置供应商和自定义供应商能力展示模型、时长和分辨率选项。

### 创建请求

前端最终调用 `API.createProject()`，主要传入：

```ts
{
  title,
  content_mode,
  aspect_ratio,
  generation_mode,
  default_duration,
  style_template_id,
  video_backend,
  image_provider_t2i,
  image_provider_i2i,
  text_backend_script,
  text_backend_overview,
  text_backend_style,
  model_settings
}
```

其中 `model_settings` 当前只保存模型级分辨率：

```json
{
  "provider/model": {
    "resolution": "2K"
  }
}
```

### 后端写入项目

后端入口：

- `plugins/manju/backend/server/routers/projects.py`
- `plugins/manju/backend/lib/project_manager.py`

后端创建项目时会写入 `project.json`：

```json
{
  "title": "项目标题",
  "content_mode": "narration",
  "aspect_ratio": "9:16",
  "generation_mode": "storyboard",
  "default_duration": 6,
  "video_backend": "ark/doubao-seedance-1-5-pro",
  "image_provider_t2i": "openai/gpt-image-2",
  "image_provider_i2i": "openai/gpt-image-2",
  "text_backend_script": "openai/gpt-5.5",
  "text_backend_overview": "openai/gpt-5.5",
  "text_backend_style": "openai/gpt-5.5",
  "model_settings": {
    "openai/gpt-image-2": {
      "resolution": "2K"
    },
    "ark/doubao-seedance-1-5-pro": {
      "resolution": "1080p"
    }
  }
}
```

当前没有保存：

- 资产图分辨率
- 分镜草稿分辨率
- 分镜最终分辨率
- 视频草稿分辨率
- 视频最终分辨率
- 每次生成使用的质量档位

## 当前全局配置与供应商逻辑

### 全局配置保存的是默认路线

相关文件：

- `plugins/manju/frontend/src/components/pages/settings/MediaModelSection.tsx`
- `plugins/manju/backend/server/routers/system_config.py`
- `plugins/manju/backend/lib/config/resolver.py`

全局设置当前保存：

```text
default_video_backend
default_image_backend_t2i
default_image_backend_i2i
text_backend_script
text_backend_overview
text_backend_style
video_generate_audio
```

也就是说，全局配置回答的是：

```text
默认用哪个供应商 / 哪个模型
```

它不是：

```text
默认每类任务用什么草稿规格 / 最终规格
```

因此草稿/最终版不应该直接塞进全局默认供应商字段里。

### 内置供应商能力

内置供应商注册表：

- `plugins/manju/backend/lib/config/registry.py`

模型能力包含：

- 媒体类型：text / image / video
- 支持能力：text_to_image / image_to_image / video
- 支持时长
- 支持分辨率
- 时长与分辨率约束
- 最大参考图数量
- 是否默认模型

典型差异：

| 供应商 | 类型 | 关键差异 |
| --- | --- | --- |
| OpenAI GPT Image | 图片 | 走图片生成/编辑接口，分辨率会映射到 OpenAI size / quality 参数 |
| Gemini Image | 图片 | 支持 image_config，包含 aspect_ratio 和 image_size |
| Ark Seedream | 图片 | 使用 size 参数，不同模型默认尺寸不同 |
| Ark Seedance | 视频 | 支持 duration、resolution、seed、audio、service_tier 等能力差异 |
| Vidu | 图片/视频 | 会根据首帧、尾帧、参考图切换 endpoint |
| Sora / NewAPI / V2 | 视频 | 接口形态和可用参数与 Ark/Vidu 不完全一致 |

### 自定义供应商是接口语义映射

相关文件：

- `plugins/manju/backend/server/routers/custom_providers.py`
- `plugins/manju/backend/lib/custom_provider/endpoints.py`
- `plugins/manju/frontend/src/components/pages/settings/CustomProviderForm.tsx`

自定义供应商通常是中转接口。它不是完全自由的黑盒，而是要选择一个 endpoint 类型，例如：

- `openai-chat`
- `gemini-generate`
- `openai-images`
- `openai-images-edits`
- `gemini-image`
- `openai-video`
- `newapi-video`
- `v2-video-generations`
- `ark-seedance`
- `vidu-video`

所以自定义供应商的真实能力应该由两部分共同决定：

```text
自定义模型配置
  + endpoint 类型能力
```

草稿/最终版方案必须尊重 endpoint 语义。比如一个自定义模型虽然叫“video”，但如果 endpoint 不支持多参考图、seed 或音频参数，就不能在最终版流程里强行传这些参数。

## 当前生成执行链路

### 前端调用

主要入口：

- `plugins/manju/frontend/src/components/canvas/StudioCanvasRouter.tsx`
- `plugins/manju/frontend/src/components/canvas/timeline/MediaCard.tsx`
- `plugins/manju/frontend/src/api.ts`

当前调用特点：

- 角色生成：只传 `prompt`
- 场景生成：只传 `prompt`
- 道具生成：只传 `prompt`
- 分镜生成：只传 `prompt`、`script_file`
- 视频生成：只传 `prompt`、`script_file`、`duration_seconds`

当前前端没有传：

- `quality`
- `resolution`
- `source_version`
- `generate_audio`
- `service_tier`
- `image_provider_t2i`
- `image_provider_i2i`
- `video_backend`

### 后端入队

主要入口：

- `plugins/manju/backend/server/routers/generate.py`
- `plugins/manju/backend/lib/generation_queue_client.py`
- `plugins/manju/backend/server/services/generation_tasks.py`

请求会被转换成 `TaskSpec` 后进入队列。

当前 `TaskSpec` 支持携带 `extra_payload`，但现有接口基本没有把草稿/最终版信息放进去。

### 图片生成

执行函数：

- `execute_character_task`
- `execute_design_task`
- `execute_storyboard_task`
- `execute_grid_task`

当前逻辑：

```text
根据任务判断是否需要图生图
  -> ConfigResolver.resolve_image_backend()
  -> resolve_resolution(project, provider, model)
  -> MediaGenerator.generate_image_async()
```

不同任务的参考图来源不同：

- 角色：可能用角色参考图做图生图
- 场景：通常文生图
- 道具：通常文生图
- 分镜：使用角色图、场景图、道具图、额外参考图、上一张分镜等
- 九宫格：使用角色/场景/道具参考图，当前没有分辨率时会保底用 `2K`

### 视频生成

执行函数：

- `execute_video_task`

当前逻辑：

```text
读取分镜图
  -> ConfigResolver.resolve_video_backend()
  -> ConfigResolver.video_capabilities()
  -> resolve_resolution(project, provider, model)
  -> 解析 duration_seconds / default_duration / 模型默认时长
  -> MediaGenerator.generate_video_async()
```

当前视频已经支持部分单次参数：

- `duration_seconds`
- `seed`
- `service_tier`

但没有质量档位，也没有按草稿/最终版解析分辨率和音频策略。

## 智能体读取配置方式

相关文件：

- `plugins/manju/backend/lib/text_generator.py`
- `plugins/manju/backend/lib/text_backends/factory.py`
- `plugins/manju/backend/lib/script_generator.py`
- `plugins/manju/backend/server/agent_runtime/sdk_tools/text_generation.py`
- `plugins/manju/backend/server/agent_runtime/sdk_tools/enqueue_assets.py`
- `plugins/manju/backend/server/agent_runtime/sdk_tools/enqueue_storyboards.py`
- `plugins/manju/backend/server/agent_runtime/sdk_tools/enqueue_videos.py`

智能体不是自己维护模型配置，它依赖项目配置和全局配置。

### 文本智能体路线

文本后端按任务类型解析：

```text
项目 text_backend_script / overview / style
  -> 全局 text_backend_script / overview / style
  -> 全局 default_text_backend
  -> 自动选择可用文本模型
```

用途：

- `overview`：分析小说，生成项目概览
- `script`：生成分集、分镜、镜头提示词
- `style`：风格相关文本

### 脚本生成会读取视频能力

`ScriptGenerator` 会读取当前项目的视频能力，并把下面信息写入提示词：

- 内容模式
- 生成模式
- 画幅
- 支持的视频时长
- 最大参考图数量
- 默认时长
- 角色、场景、道具
- 项目风格

所以供应商能力已经会影响文本脚本结果，但目前没有草稿/最终版概念。

### 智能体生成资产、分镜、视频

当前智能体工具：

- `generate_assets`
- `generate_storyboards`
- `generate_video_episode`
- `generate_video_scene`
- `generate_video_all`
- `generate_video_selected`

它们最终也是创建 `TaskSpec` 入队。

当前缺口：

- 资产工具没有声明默认 final
- 分镜工具没有声明 draft/final
- 视频工具没有声明 draft/final
- 工具返回结果没有报告实际 provider / model / resolution / quality

如果只改 Web 前端按钮，智能体批量生成仍然会走旧的项目单套配置。

## 为什么不能只用项目默认 1K / 720p

如果创建项目时设置图片 1K、视频 720p，那么会影响：

- 角色图
- 场景图
- 道具图
- 分镜图
- 视频片段

这会导致：

- 母资产低质量，后续参考图质量不稳
- 最终视频可能混入低规格分镜
- 只把某些镜头升到 1080p 时，前后片段规格不一致
- 低规格满意后重新高规格生成，仍可能重新抽卡走偏
- 导出前无法准确知道哪些素材还是草稿

因此需要在数据结构里明确记录：

```text
这个版本是草稿还是最终版
这个版本由哪个供应商/模型生成
这个版本的分辨率和时长是什么
这个视频基于哪个分镜版本生成
```

## 图片输入、视频稳定性与低消耗策略

这一节合并自 `docs/manju漫剧短剧图片视频生成方案.md`。它补充的是执行层策略：如何降低无用 token / 请求体消耗，以及如何提升图生视频稳定性。

### 行业生产流水线

当前主流 AI 漫剧 / 短剧生产不推荐直接“长文本一键生成完整视频”。更稳定的链路是：

```text
剧本拆解
  -> 角色 / 场景 / 道具资产库
  -> 分镜脚本
  -> 分镜关键帧图片
  -> 图生视频逐镜头生成
  -> 剪辑合成 / 配音 / 字幕 / 音效
```

核心思想是：先用图片锁定静态事实，再让视频模型负责运动表现。

这样做的原因：

- 视频模型在长跨度内保持角色一致性仍然不稳定。
- 图生视频比文生视频更容易控制角色、服装、场景和构图。
- 先生成关键帧可以提前发现错误，避免直接生成视频造成更高重试成本。
- 镜头级拆分便于失败重试、人工挑选、版本回滚和成本统计。

### 当前图片与视频文件现状

当前项目已有的基础方向是正确的：

- `lib/resource_paths.py` 将分镜、角色、场景、道具、宫格图的标准路径定义为 `.png`。
- `lib/media_generator.py` 统一调度图片生成和视频生成。
- `lib/image_backends/*` 负责图片供应商。
- `lib/video_backends/*` 负责视频供应商。
- `lib/image_utils.py` 已经包含上传图片压缩逻辑。

需要注意：当前“路径后缀”和“真实图片编码”不一定一致。

可能出现：

- 文件名是 `.png`，真实内容是 PNG。
- 文件名是 `.png`，真实内容实际是 JPEG。
- 用户上传图片超过阈值后被压缩为 JPEG，并改为 `.jpg` 后缀。

这不是立即阻断功能的问题，但会影响后续上传给供应商时的 MIME 判断、Base64 体积和请求稳定性。

### 母版、关键帧和图生视频

角色、场景、道具应先生成母版：

- 角色：正面半身、全身、表情、服装、关键饰品。
- 场景：主视角、光照氛围、可复用构图。
- 道具：清晰单体图，必要时包含使用状态。

母版图的目标是“定义身份”，不是直接做最终镜头。

每个分镜应先生成关键帧，并检查：

- 角色是否正确。
- 服装、发型、道具是否正确。
- 人物站位和镜头景别是否正确。
- 场景和光照是否符合剧情。
- 画面中是否出现多余人物、错手、错物、文字污染。

只有关键帧通过后，再进入图生视频。

### 视频 prompt 精简策略

图生视频时，视频 prompt 应主要描述运动和镜头，不要重复描述所有静态画面。

原因：

- 角色、服装、场景、构图已经由分镜图锁定。
- 重复塞入静态描述会浪费文本 token。
- 过多静态描述可能让视频模型重新发散理解，反而降低稳定性。

推荐视频 prompt 结构：

```text
主体动作 + 镜头运动 + 情绪变化 + 环境运动 + 禁止项
```

示例：

```text
女子缓慢转身看向门外，表情从警惕变为震惊。镜头轻微前推，烛火闪动，衣摆随风轻动。保持人物身份、服装和场景一致，不要改变脸型，不要新增人物。
```

后续改造时，分镜脚本可继续保存完整静态描述，但传给视频模型前应生成一个更短的 `video_motion_prompt`：

```text
script item 全量描述
  -> 提取动作 / 镜头 / 情绪 / 环境运动 / 禁止项
  -> 与分镜图一起提交给视频供应商
```

### 首帧、尾帧和多参考图策略

默认图生视频应优先使用分镜图作为首帧。

复杂镜头可以使用首帧 + 尾帧：

- 人物从站立变为跪地。
- 人物从门外走到桌前。
- 镜头从远景推进到特写。
- 道具从手中落到地上。

首帧 + 尾帧比只传首帧更容易控制动作终点，但前提是供应商模型支持 last frame。

多参考图适合：

- 一个镜头里必须同时保持多个角色。
- 角色 + 道具 + 场景都很关键。
- 使用供应商明确支持 reference images 的端点。

多参考图不是越多越好。过多参考会造成：

- 模型不知道哪个参考优先。
- 角色特征互相污染。
- 请求体过大。
- 生成失败率升高。

建议默认限制：

- 普通分镜：1 张首帧。
- 角色关键镜头：首帧 + 1 张角色母版。
- 多人关键镜头：首帧 + 2-3 张角色母版。
- 超过 3 张参考图时，优先合成一张干净的分镜关键帧，而不是直接把所有参考塞给视频模型。

### 供应商输入图片准备层

建议新增一个“供应商输入图片准备层”，不要让各个图片/视频 backend 直接读取原始文件并自行决定格式。

建议接口：

```text
prepare_provider_image_input(
    source_path,
    provider,
    purpose="image_to_video" | "image_to_image",
    max_long_edge=2048,
    jpeg_quality=90,
)
```

输出：

- 临时图片路径。
- 真实 MIME 类型。
- 原图大小。
- 优化后大小。
- 是否发生压缩 / 转码。

保存策略：

```text
原始母版图：尽量保留供应商原始输出，不破坏质量。
供应商输入图：按目标供应商、用途和视频分辨率生成临时优化副本。
```

不要为了降低上传体积直接覆盖母版图。

视频供应商输入图建议：

- 默认长边限制：2048px。
- 默认 JPEG 质量：90。
- 有透明通道、线稿、文字、小道具细节时保留 PNG。
- 普通角色、场景、分镜图可以使用高质量 JPEG。
- 按真实文件头判断图片类型，不只看文件后缀。

原因：

- PNG 无损但体积大，Base64 后还会膨胀约 33%。
- 高质量 JPEG 对图生视频通常足够，尤其输出视频为 720p / 1080p 时。
- 过大的 PNG 不一定提升视频质量，但会增加上传时间、请求体大小和失败概率。

对 Vidu / NewAPI / V2 等请求体敏感供应商，提交前应估算 Base64 后大小，并提前失败或提示，而不是等供应商返回 400。

### 镜头档位

除了 draft/final，还可以按镜头重要程度增加 S / A / B 档位。

| 档位 | 场景 | 推荐策略 |
| --- | --- | --- |
| S 档 | 主角特写、剧情高潮、封面、宣传片段 | 高质量图片模型 + 高质量视频模型，允许更多重试 |
| A 档 | 普通剧情镜头、人物对话、关键转场 | 标准图片模型 + 稳定图生视频模型 |
| B 档 | 过场、环境、低关注镜头、批量测试 | 快速 / 低成本模型，失败后可降级处理 |

S / A / B 和 draft/final 的关系：

```text
draft/final 决定生产阶段
S/A/B 决定镜头重要程度
```

例如：

```text
B 档 draft：快速低成本试镜头
A 档 final：普通成片规格
S 档 final：主角特写或高潮镜头，允许更高模型、更高重试预算
```

后续可在 `generation_profiles` 外增加 `shot_tiers`：

```json
{
  "shot_tiers": {
    "S": {
      "retry_budget": 3,
      "prefer_first_last_frame": true,
      "allow_extra_reference_images": true
    },
    "A": {
      "retry_budget": 2
    },
    "B": {
      "retry_budget": 1,
      "allow_fallback_model": true
    }
  }
}
```

### 供应商选择补充标准

图片供应商优先看：

- 角色一致性。
- 对参考图的服从能力。
- 输出分辨率和细节。
- 风格稳定性。
- 响应中是否返回准确 usage / credits。
- 图片审核误伤率。

图片模型使用建议：

- 角色母版和关键分镜使用更高质量模型。
- 批量普通分镜使用成本更低、速度更快的模型。
- 同一项目尽量减少频繁切换图片模型，避免风格漂移。

视频供应商优先看：

- 是否支持 image-to-video。
- 是否支持 first frame + last frame。
- 是否支持 reference images。
- 是否支持目标时长和分辨率。
- 人脸稳定性。
- 镜头运动自然度。
- 失败重试成本。
- 是否能返回 provider job id，便于断点续轮询，避免重复扣费。

视频模型使用建议：

- 默认走图生视频，不优先走文生视频。
- 重要镜头优先选高质量模型。
- 大批量镜头优先选稳定、便宜、速度快的模型。
- 需要精确动作终点时，优先选支持首尾帧的模型。

### 成本与质量判断

图片 PNG / JPEG 的文件体积本身通常不是主要计费维度。

更常见的计费维度是：

- 图片生成：模型、输出尺寸、质量档位、图片 token、张数。
- 图生图：输入图片 token / 图片数量、输出尺寸、模型。
- 视频生成：模型、时长、分辨率、是否生成音频、服务档位。
- Vidu 类平台：credits / 积分。
- Ark 类平台：token 或按模型规格估算。

因此：

- 压缩图片主要降低上传体积、请求耗时和请求体限制风险。
- 压缩图片不一定显著降低供应商费用。
- 真正影响成本的是分辨率、时长、模型档位和失败重试次数。

质量上：

- PNG 更适合母版、线稿、透明图、文字和小道具。
- JPEG 90 通常适合作为图生视频输入。
- JPEG 质量过低会造成脸部细节损失、边缘伪影和纹理污染。
- 尺寸过小会导致角色身份漂移和细节丢失。
- 尺寸过大可能没有质量收益，只增加请求失败率。

### 推荐默认参数

图片输入优化：

| 用途 | 格式 | 长边 | 质量 | 说明 |
| --- | --- | --- | --- | --- |
| 角色母版保存 | 原始格式 | 不强制缩放 | 不压缩 | 作为可回溯母版 |
| 普通图生视频输入 | JPEG | 2048px | 90 | 默认推荐 |
| 关键镜头图生视频输入 | JPEG 或 PNG | 2048-3072px | 90-95 | 视供应商限制调整 |
| 线稿 / 文字 / 透明图 | PNG | 2048px | 无损 | 避免 JPEG 伪影 |
| 多参考图批量输入 | JPEG | 1536-2048px | 88-90 | 控制请求体大小 |

视频生成：

| 镜头类型 | 输入 | 分辨率 | 时长 | 策略 |
| --- | --- | --- | --- | --- |
| 普通镜头 | 首帧 | 720p / 1080p | 4-8 秒 | 成本优先 |
| 关键剧情 | 首帧 + 尾帧 | 1080p | 5-8 秒 | 准确性优先 |
| 主角特写 | 首帧 + 角色母版 | 1080p | 4-6 秒 | 身份一致性优先 |
| 复杂动作 | 首帧 + 尾帧 | 1080p | 6-10 秒 | 动作终点优先 |
| 批量预览 | 首帧 | 720p | 3-5 秒 | 快速筛选 |

## 推荐配置结构

建议新增 `generation_profiles`，替代只用简单 `quality_settings` 的方案。

原因是草稿/最终版不只是分辨率，还可能包含：

- 供应商
- 模型
- 分辨率
- 时长
- 是否生成音频
- service_tier
- seed 策略
- 参考图数量限制

示例：

```json
{
  "generation_profiles": {
    "asset": {
      "image_provider_t2i": null,
      "image_provider_i2i": null,
      "resolution": "2K"
    },
    "storyboard_draft": {
      "image_provider_t2i": null,
      "image_provider_i2i": null,
      "resolution": "1K"
    },
    "storyboard_final": {
      "image_provider_t2i": null,
      "image_provider_i2i": null,
      "resolution": "2K"
    },
    "grid": {
      "image_provider_t2i": null,
      "image_provider_i2i": null,
      "resolution": "2K"
    },
    "video_draft": {
      "video_backend": null,
      "resolution": "720p",
      "duration_seconds": null,
      "generate_audio": false,
      "service_tier": "default"
    },
    "video_final": {
      "video_backend": null,
      "resolution": "1080p",
      "duration_seconds": null,
      "generate_audio": true,
      "service_tier": "default"
    },
    "reference_video_draft": {
      "video_backend": null,
      "resolution": "720p",
      "duration_seconds": null,
      "generate_audio": false,
      "service_tier": "default"
    },
    "reference_video_final": {
      "video_backend": null,
      "resolution": "1080p",
      "duration_seconds": null,
      "generate_audio": true,
      "service_tier": "default"
    }
  }
}
```

说明：

- `null` 表示继承项目当前模型路线。
- 如果用户希望草稿视频走便宜模型，最终视频走高质量模型，可以在 profile 内单独指定。
- 旧项目没有 `generation_profiles` 时，继续使用现有 `model_settings` 和项目默认字段。

## 推荐解析优先级

新增统一解析逻辑，例如：

```py
resolve_generation_route(project, payload, task_kind, quality, capability)
```

解析优先级：

```text
1. payload 显式覆盖
2. project.generation_profiles[profile_key]
3. project 当前模型路线和 model_settings
4. 全局默认供应商
5. 自动选择可用供应商
```

其中 `profile_key` 映射建议：

```text
character -> asset
scene -> asset
prop -> asset
storyboard + draft -> storyboard_draft
storyboard + final -> storyboard_final
grid -> grid
video + draft -> video_draft
video + final -> video_final
reference_video + draft -> reference_video_draft
reference_video + final -> reference_video_final
```

`grid` 是宫格镜头板，不再接受低清草稿语义。即使调用方误传 `quality=draft`，后端也应按 `grid` profile 执行，避免整张宫格 1K 导致单格参考图过小。

能力校验必须在解析后执行：

- 供应商是否支持对应媒体类型
- 图片是否支持文生图 / 图生图
- 视频是否支持当前参考图数量
- 视频是否支持当前时长
- 视频是否支持当前分辨率
- 当前分辨率和时长是否存在绑定约束
- 是否支持音频
- 是否支持 seed
- 是否支持 service_tier

## API 参数建议

新增统一生成参数：

```ts
type GenerationQuality = "draft" | "final" | "custom";

interface GenerationOptions {
  quality?: GenerationQuality;
  resolution?: string;
  source_version?: number;
  image_provider_t2i?: string;
  image_provider_i2i?: string;
  video_backend?: string;
  duration_seconds?: number;
  generate_audio?: boolean;
  service_tier?: string;
  seed?: number;
}
```

分镜请求示例：

```json
{
  "prompt": {},
  "script_file": "episode_1.json",
  "quality": "draft"
}
```

视频请求示例：

```json
{
  "prompt": {},
  "script_file": "episode_1.json",
  "quality": "final",
  "source_version": 3
}
```

需要注意：`duration_seconds` 不应由前端 API 默认写死为 4。没有明确传入时，应让后端按 profile、项目默认时长、模型默认时长解析。

## 前端改造方案

### 创建项目

创建项目继续保留简单体验，但分辨率区域改成生成策略：

- 资产图片规格
- 分镜草稿规格
- 分镜最终规格
- 宫格镜头板规格
- 视频草稿规格
- 视频最终规格
- 参考视频草稿规格
- 参考视频最终规格

高级模式可以允许：

- 草稿图像模型
- 最终图像模型
- 草稿视频模型
- 最终视频模型

默认可以全部继承当前项目模型路线，只覆盖规格。

当前实现状态：

- 默认创建路径保持简单体验：未启用高级策略时，仍按创建向导里的图片 / 视频分辨率生成默认 `generation_profiles`。
- 创建向导第二步已增加“生成质量策略”高级区，用户启用后可直接编辑母版、分镜草稿、分镜最终版、宫格、视频草稿、视频最终版、参考视频草稿、参考视频最终版的分辨率与视频音频策略。
- 高级区未启用时不会覆盖用户原有创建习惯；高级区启用后才把编辑后的完整 `generation_profiles` 写入项目。

### 项目设置

新增“生成质量策略”区块：

- 母资产
- 分镜草稿
- 分镜最终版
- 宫格镜头板
- 视频草稿
- 视频最终版
- 参考视频草稿
- 参考视频最终版

每一项显示：

- 继承哪个模型
- 当前分辨率
- 当前时长
- 是否生成音频
- 是否存在供应商能力警告

当前实现状态：

- 当前选中镜头的分镜 / 视频卡片会读取当前版本元数据，并展示质量、分辨率、时长、供应商模型、是否生成音频等徽标。
- 视频卡片会展示供应商输入图是否经过优化 / 校验，以及当前视频是否基于最终分镜、草稿分镜、自定义分镜或宫格镜头板单格。
- 这些状态来自版本元数据，不依赖前端猜测。

### 资产库页面

角色、场景、道具默认按钮保持简单：

```text
生成母版
```

默认行为：

```text
quality = final
profile = asset
```

原因：这些是后续分镜的稳定参考源，不建议默认草稿。

### 分镜卡片

分镜生成按钮建议拆成：

- 生成草稿
- 生成最终版

默认按钮可以是“生成草稿”，旁边下拉提供“生成最终版”。

行为：

```text
生成草稿 -> quality=draft -> storyboard_draft
生成最终版 -> quality=final -> storyboard_final
```

### 宫格镜头板

宫格模式不显示单分镜“草稿/最终版”按钮。宫格图一张图包含多个分镜，整图 1K 会导致单格过小，因此宫格入口应显示为：

```text
生成宫格镜头板 -> profile=grid -> 使用项目图片规格，默认 2K
```

宫格切分出来的单格图就是宫格生视频模式的视频首帧来源，不再要求额外“单格高清化”或“单格最终化为单分镜”。该模式的质量基准由宫格整图 profile 和项目图片规格保障；最终化 / 导出检查应把 `grid` 来源视为该模式下的最终可用来源，而不是把它误判为缺少单张最终分镜。

### 参考生视频

参考生视频跳过分镜图，使用角色/场景/道具参考图直接生成视频，因此不复用 `storyboard_draft/final`。其按钮建议拆成：

```text
参考视频草稿 -> quality=draft -> reference_video_draft
参考视频最终版 -> quality=final -> reference_video_final
```

当前 agent 视频工具在 `reference_video` 模式下已经支持单 unit / 多 unit 精确选择：`generate_video_scene.scene_id` 视为 `unit_id`，`generate_video_selected.scene_ids` 视为 `unit_id` 列表，不再自动退化成整集生成。草稿/最终版仍只改变 profile 路由和分辨率等生成参数，unit 时长继续跟随脚本里的实际 `duration_seconds`。

参考生视频必须使用支持参考图输入的视频模型。若 route preview 或执行期发现模型 `max_reference_images=0`，应直接报错并提示切换模型；不能把参考图裁成 0 张后继续生成，否则会把 reference_video 静默退化成 text-to-video，破坏资产一致性。

### 视频卡片

视频生成按钮建议拆成：

- 生成草稿视频
- 生成最终视频

行为：

```text
生成草稿视频 -> quality=draft -> video_draft
生成最终视频 -> quality=final -> video_final
```

生成最终视频前建议检查：

- 当前分镜图是否存在
- 当前分镜图是否为最终版，或在宫格生视频模式下是否为 `grid` 来源
- 当前分镜图的分辨率是否满足最终要求
- 当前供应商是否支持最终视频参数

### 最终化入口

建议新增“最终化本集”。

逻辑：

```text
1. 扫描本集全部镜头
2. 检查母资产是否存在
3. 检查分镜是否已有最终版；宫格生视频模式下 `grid` 来源视为最终可用来源
4. 对缺少最终分镜且非 `grid` 来源的镜头生成最终分镜
5. 对缺少最终视频的镜头生成最终视频
6. 输出最终化报告
```

报告示例：

```text
最终化完成
- 最终分镜：28/30
- 最终视频：30/30
- 失败镜头：2
```

## 后端改造方案

### 请求模型

在这些请求模型中增加可选字段：

- `GenerateStoryboardRequest`
- `GenerateVideoRequest`
- `GenerateCharacterRequest`
- `GenerateSceneRequest`
- `GeneratePropRequest`

建议字段：

```py
quality: Literal["draft", "final", "custom"] | None = None
resolution: str | None = None
source_version: int | None = None
image_provider_t2i: str | None = None
image_provider_i2i: str | None = None
video_backend: str | None = None
generate_audio: bool | None = None
service_tier: str | None = None
seed: int | None = None
```

视频继续支持：

```py
duration_seconds: int | None = None
```

### 入队 payload

`TaskSpec.from_request()` 可以继续使用 `extra_payload`。

写入前过滤 `None`：

```py
extra_payload = compact_dict({
    "quality": req.quality,
    "resolution": req.resolution,
    "source_version": req.source_version,
    "video_backend": req.video_backend,
    "image_provider_t2i": req.image_provider_t2i,
    "image_provider_i2i": req.image_provider_i2i,
    "duration_seconds": req.duration_seconds,
    "generate_audio": req.generate_audio,
    "service_tier": req.service_tier,
    "seed": req.seed,
})
```

### 解析器

建议新增服务：

```text
backend/server/services/generation_route_resolver.py
```

职责：

- 根据任务类型和 quality 选择 profile
- 合并 payload 覆盖、profile、项目默认、全局默认
- 返回 provider、model、resolution、duration、generate_audio、service_tier
- 执行供应商能力校验
- 生成用于版本记录的 metadata

不要把所有逻辑塞进 `resolution_resolver.py`，因为草稿/最终版不只是分辨率。

### 执行任务

需要接入新解析器的函数：

- `execute_character_task`
- `execute_design_task`
- `execute_storyboard_task`
- `execute_grid_task`
- `execute_video_task`

当前：

```py
image_size = await resolve_resolution(project, provider_id, model_id)
```

目标：

```py
route = await resolve_generation_route(
    project,
    payload=payload,
    task_kind="storyboard",
    quality=payload.get("quality"),
    capability="image_to_image" if refs else "text_to_image",
)

image_size = route.resolution
```

视频同理：

```py
route = await resolve_generation_route(
    project,
    payload=payload,
    task_kind="video",
    quality=payload.get("quality"),
    capability="video",
)
```

### 版本记录

`MediaGenerator.generate_image_async()` 和 `generate_video_async()` 已经支持版本 metadata。

建议每次生成都记录：

```json
{
  "quality": "draft",
  "profile_key": "storyboard_draft",
  "provider_id": "openai",
  "model": "gpt-image-2",
  "resolution": "1K",
  "source_version": 2
}
```

视频额外记录字段：

```text
duration_seconds: 实际镜头或 reference_video unit 时长，不因为 draft/final 固定成某个秒数
generate_audio: 是否生成音频
service_tier: 供应商支持的服务档位
seed: 供应商支持时记录 seed
source_storyboard_version: 视频来源分镜版本
```

还建议在分镜数据里保存当前激活资产的简要 metadata，例如：

```json
{
  "generated_assets_meta": {
    "storyboard_image": {
      "quality": "draft",
      "resolution": "1K"
    },
    "video_clip": {
      "quality": "draft",
      "resolution": "720p"
    }
  }
}
```

这样前端和导出流程不用读取完整版本历史，也能快速判断当前素材是否能用于最终导出。

## 智能体工具改造方案

智能体工具必须同步支持质量档位。

### 资产生成工具

`generate_assets` 默认：

```text
quality = final
profile = asset
```

可选参数：

- `quality`
- `resolution`
- `image_provider_t2i`
- `image_provider_i2i`

### 分镜生成工具

`generate_storyboards` 默认：

```text
quality = draft
profile = storyboard_draft
```

可选参数：

- `quality`
- `resolution`
- `source_version`
- `image_provider_t2i`
- `image_provider_i2i`

### 视频生成工具

`generate_video_episode`、`generate_video_scene`、`generate_video_all`、`generate_video_selected` 默认：

```text
quality = draft
profile = video_draft
```

可选参数：

- `quality`
- `resolution`
- `duration_seconds`
- `video_backend`
- `generate_audio`
- `service_tier`
- `seed`
- `source_version`

`reference_video` 模式下，`generate_video_scene` 和 `generate_video_selected` 的 ID 参数映射到 `video_units[*].unit_id`，用于只生成指定参考视频 unit；`generate_video_episode` / `generate_video_all` 仍生成整集缺失 unit。reference_video 入队 payload 已携带 `quality` 和 unit 的实际 `duration_seconds`。

### 能力查询工具

`get_video_capabilities` 建议扩展返回：

- 支持分辨率
- 时长与分辨率约束
- 最大参考图数量
- 是否支持音频
- 是否支持 seed
- 是否支持 service_tier
- 当前 draft/final profile 解析后的推荐参数

否则智能体无法解释“为什么 1080p 不能选 6 秒”这类供应商差异。

## 供应商能力需要补齐的地方

当前 `ConfigResolver.video_capabilities()` 已经能返回：

- provider
- model
- supported_durations
- max_duration
- max_reference_images
- default_duration
- content_mode
- generation_mode

建议补齐：

- `resolutions`
- `duration_resolution_constraints`
- `supports_audio`
- `supports_seed`
- `supports_service_tier`
- `endpoint_family`

对自定义供应商，能力来源建议：

```text
custom model 配置
  + endpoint registry
  + 对应内置后端的能力推断
```

例如：

- `ark-seedance` endpoint 应尽量复用 Ark Seedance 能力判断。
- `vidu-video` endpoint 应尽量复用 Vidu 能力判断。
- OpenAI-compatible / NewAPI / V2 endpoint 应声明自己的默认能力边界。

## 导出前检查

导出成片前建议增加质量检查：

- 是否存在缺视频镜头
- 是否存在草稿视频
- 是否存在低于最终规格的视频
- 是否存在视频基于草稿分镜生成
- 是否存在母资产缺失
- 是否存在供应商/模型信息缺失的历史素材

提示示例：

```text
当前项目仍有草稿视频或低规格素材，建议先执行“最终化本集”。
```

如果用户仍要导出，可以允许继续，但应明确标记风险。

## 流程闭环审查

本节用于审查方案是否真正闭环。闭环的标准不是“能发起生成”，而是：

```text
配置可保存
前端可选择
后端可解析
供应商可执行
失败可解释
结果可追踪
导出可检查
旧项目可兼容
```

### 闭环审查表

| 流程 | 当前状态 | 闭环完成情况 |
| --- | --- | --- |
| 创建项目 | 已完成 | 创建时写入默认 `generation_profiles`；旧字段 `model_settings` 保留；高级区启用后可编辑完整 profile；创建后能在项目设置回显 |
| 项目设置 | 已完成 | 已能编辑并保存母资产、分镜、宫格、视频、参考视频 profile 和 S/A/B 档位策略；模型/分辨率/档位变化会触发后端 route preview 即时校验并展示错误、降级警告、历史推荐和质量统计 |
| 角色/场景/道具生成 | 已完成 | 手动与智能体默认 `quality=final`；新生成版本写入 provider/model/resolution/quality metadata；旧项目走兼容读取，不在迁移时覆盖用户历史自定义 |
| 分镜草稿 | 已完成 | 前端传 `quality=draft`；后端解析 `storyboard_draft`；版本记录草稿标记；可作为最终分镜来源 |
| 分镜最终版 | 已完成 | 已有 `quality=final` 和 `source_version` 入口；最终版生成会优先把当前草稿分镜或指定版本作为 I2I 参考，并在新版本 metadata 记录来源分镜版本、文件和质量；S/A/B 策略可控制是否保留该来源 |
| 宫格镜头板 | 已完成 | 已拆成独立 `grid` profile，不走低清草稿；切分单格会写入来源宫格版本、文件、grid id 和 cell index metadata；宫格生视频不要求单格再高清化，最终化/导出检查可把 grid 来源视为最终可用来源 |
| 视频草稿 | 已完成 | 前端传 `quality=draft`；后端解析 `video_draft`；时长跟随实际镜头时长、项目设置或模型能力，不固定 6 秒；生成后记录来源分镜版本 |
| 视频最终版 | 已完成 | 已支持 `quality=final` 和 `video_final` 路由；默认阻止最终视频基于草稿分镜生成，B 档等显式策略可放宽；供应商分辨率/时长/音频由 route resolver 校验和降级提示 |
| 参考视频草稿/最终版 | 已完成 | 已支持 `reference_video_draft/final` profile、版本 metadata、单 unit / 多 unit 精确选择；草稿/最终版不固定时长，继续使用 unit 实际时长 |
| 智能体资产生成 | 已完成 | `generate_assets` 默认 `quality=final`，并把质量档位写入 TaskSpec payload |
| 智能体分镜生成 | 已完成 | `generate_storyboards` 默认 `quality=draft`，允许显式 `final` |
| 智能体宫格生成 | 已完成 | `generate_grid` 不提供低清草稿，默认 `quality=final` / `profile=grid` |
| 智能体视频生成 | 已完成 | `generate_video_*` 默认 `quality=draft`，允许 `final`；普通视频和 reference_video 都携带实际 `duration_seconds`；reference_video 单 unit / 多 unit 精确选择已补齐 |
| 能力查询工具 | 已完成 | `get_video_capabilities` 返回 `agent_generation_defaults` 与 `quality_recommendations.video/reference_video.draft/final` |
| 版本面板 / 卡片 | 已完成 | 当前卡片已展示质量、分辨率、供应商、模型、时长、输入图优化状态、来源分镜质量，并可记录人工总体评分和角色一致性/动作自然度等维度评分 |
| 最终化本集 | 已完成 | 已新增本集最终化入口：扫描缺失/非最终分镜和视频；宫格生视频下 grid 来源视为最终可用来源；普通图生视频缺失最终分镜时批量提交最终分镜/最终视频任务，并让最终视频依赖刚提交的最终分镜；任务完成后可通过最终化报告接口汇总失败项、失败类型和重试建议 |
| 导出成片 | 已完成 | 剪映导出前已拦截草稿视频、基于草稿分镜的视频，以及明确低于最终 profile 分辨率的视频；导出前问题统计和最终化报告共同提供可视化检查依据 |
| 旧项目兼容 | 已完成 | 没有 `generation_profiles` 时会规范化默认 profile 并兼容旧 `model_settings`；迁移/读取采用保守合并，不覆盖用户历史自定义 |
| 自定义供应商 | 已完成 | 后端能力解析已参与 profile 路由；项目设置 route preview 会按 endpoint registry、模型配置和实际 backend 能力共同校验，避免只看前端静态选项 |
| 真实图片类型检测 | 已完成 | 供应商输入前读取文件头判断 MIME，不只依赖 `.png/.jpg` 后缀 |
| 供应商输入图片准备层 | 已完成 | `prepare_provider_image_input` 生成临时优化副本；原始母版不被覆盖；版本 metadata 记录路径、MIME、大小和转码信息 |
| 临时输入图生命周期 | 已完成 | 临时优化副本使用稳定 cache key；任务成功后清理并记录 `cleaned_up`，失败时保留临时输入图用于诊断；启动时会清理过期临时输入图 |
| 视频 prompt 精简 | 已完成 | 执行层统一从结构化 `video_prompt` 提炼 motion prompt，减少无效 token，并保留原始信息供回溯 |
| 首帧/尾帧/多参考图选择 | 已完成 | 已受供应商参考图能力和 S/A/B 参考图策略约束；超限时按能力/策略截断并记录原始数量、提交数量、丢弃数量和原因 |
| 请求体大小控制 | 已完成 | 已对 Base64 膨胀大小做预估，并对请求体敏感供应商提前警告或失败；供应商输入图优化和参考图截断共同降低请求体风险 |
| S/A/B 镜头档位 | 已完成 | 已有字段、WebUI 切换、agent patch、项目级默认策略、单镜头覆盖、模型/分辨率/参考图策略/重试预算绑定，并进入路由和 worker 重试逻辑 |
| 成本与质量统计 | 已完成 | 已记录人工评分、失败类型、角色一致性/动作自然度等维度评分、供应商成功率；项目设置使用历史成功率推荐默认模型并展示质量统计 |

### 闭环关键点

最容易漏掉的是这几处：

1. **最终版来源闭环**
   分镜最终版和视频最终版必须记录来源版本。否则用户无法知道 1080p 视频到底是基于哪个分镜图生成的。

2. **智能体路径闭环**
   手动按钮支持 draft/final 还不够。智能体批量生成资产、分镜、视频也必须传同一套质量参数，否则自动流程会绕过新策略。

3. **导出检查闭环**
   如果只在版本历史里记录 metadata，而当前分镜数据没有简要 `generated_assets_meta`，导出检查会变重，也更容易漏判。建议两边都存：版本历史保存完整信息，当前分镜保存快速判断信息。

4. **供应商输入图闭环**
   输入图优化不能只做成工具函数。它必须进入所有 I2I / I2V / reference video backend 的统一入口，并记录压缩、转码、真实 MIME、请求体预估大小。

5. **视频稳定性闭环**
   视频质量不只由分辨率决定，还由首帧、尾帧、参考图数量、motion prompt 长度和供应商 endpoint 决定。最终版视频必须把这些信息写入 metadata。

6. **成本统计闭环**
   如果不记录失败类型、输入图大小、重试次数和供应商返回 job id，就无法判断“低消耗策略”是否真的降低了无用 token / 请求体消耗。

## 供应商和模型适配审查

供应商适配不能只看“这个供应商支持图片/视频”，必须落到具体模型和 endpoint。

建议以三层真相源为准：

```text
内置模型注册表 registry.py
  + 自定义供应商 endpoint registry
  + 实际 backend 参数翻译层
```

如果三层不一致，前端可能展示可选，后端也能入队，但最终供应商会 400、静默降级或生成出错误规格。

### 文本模型适配

| 类型 | 当前适配点 | 审查结论 |
| --- | --- | --- |
| OpenAI 文本 | `openai` text backend | 可作为脚本/概览/风格路线；需要确保结构化输出任务能稳定返回 schema |
| Gemini 文本 | `gemini-aistudio` / `gemini-vertex` | 可作为文本路线；schema 输出能力应作为脚本/概览任务的校验项 |
| Ark / 豆包文本 | `ark` / `ark-agent-plan` | 部分模型只有 `text_generation` 或 `vision`，不是所有模型都声明 `structured_output`；脚本/概览这类 schema 任务需要额外校验或 JSON fallback |
| Grok 文本 | `grok` text backend | 注册表声明结构化能力；适合进入文本路线，但仍需按任务类型校验 |
| 自定义文本 | `openai-chat` / `gemini-generate` | endpoint 能证明媒体类型是 text，但不能天然证明结构化输出可靠；需要在配置页或运行时标记 schema 能力 |

文本模型不直接参与草稿/最终版，但它决定角色集、场景集、道具集、分镜脚本和视频提示词质量。建议增加文本任务能力校验：

```text
overview/script/style 使用 response_schema 时
  -> 优先选择声明 structured_output 的模型
  -> 未声明时允许使用，但必须走 JSON 解析/修复 fallback
  -> 失败提示应说明“当前文本模型不适合结构化任务”
```

### 图片模型适配

| 供应商/endpoint | 模型差异 | 草稿/最终版适配要求 |
| --- | --- | --- |
| OpenAI 图片 | GPT Image 系列支持 T2I/I2I；`512px/1K/2K` 会映射为 size/quality | 分镜草稿可用 1K；母资产/最终分镜可用 2K；不应给它展示 4K |
| Gemini 图片 | Gemini Image 支持 T2I/I2I；常见 `1K/2K/4K` | 可支持 1K 草稿、2K/4K 终版；后端要透传 `image_config` |
| Ark Seedream | Seedream 支持 T2I/I2I；显式 size 会影响画幅；不传 size 可能默认 1:1 | 必须按项目画幅和 profile 分辨率解析 size；母资产建议 2K |
| Grok Image | 注册表声明 T2I/I2I，常见 `1K/2K` | 可支持草稿/最终，但最终不能要求 4K |
| Vidu Image q2 | 支持 T2I/I2I，`1080p/2K/4K` | 可做母资产和最终图；分辨率需按白名单校验 |
| Vidu Image q1 | 只支持 I2I，且常见只有 `1080p` | 不能作为文生图 T2I 路线；只能作为图生图/编辑路线 |
| 自定义 `openai-images` | 同时支持 T2I/I2I | 可继承 OpenAI 图片参数策略，但真实分辨率仍可能取决于中转站 |
| 自定义 `openai-images-generations` | 只支持 T2I | 不能用于分镜 I2I、角色参考图 I2I、最终分镜高清化 |
| 自定义 `openai-images-edits` | 只支持 I2I | 不能用于无参考图的角色/场景/道具文生图 |
| 自定义 `gemini-image` | T2I/I2I | 可走 Gemini 图片策略，但仍要按模型实际支持检查分辨率 |

图片适配必须保留两个独立槽位：

```text
image_provider_t2i
image_provider_i2i
```

原因是有些模型/endpoint 只支持其中一种能力。分镜最终版如果要基于草稿图 I2I，就必须确保最终 profile 的 I2I 路线可用。

### 视频模型适配

| 供应商/endpoint | 模型差异 | 草稿/最终版适配要求 |
| --- | --- | --- |
| Gemini Veo AI Studio | 4/6/8 秒；720p/1080p；部分模型 1080p 只能配 8 秒；参考图上限约 3 | `video_final=1080p` 时必须校验时长约束，不能默认 6 秒 |
| Gemini Veo Vertex | 4/6/8 秒；720p/1080p；部分模型支持音频 | 需要区分是否支持 `generate_audio`，并把能力返回给前端/智能体 |
| Ark Seedance 1.5 | 4-12 秒；480p/720p/1080p；支持音频、seed、flex tier；注册表声明参考图上限 9 | 草稿 720p + 实际镜头时长适配；最终 1080p 适配；service_tier 只在支持 flex 的模型传 |
| Ark Seedance 2.0 / 2.0 Fast | 4-15 秒；480p/720p/1080p；支持音频、seed、视频扩展；不应传 flex tier | 草稿/最终都适配；必须避免给 2.0 传 `service_tier=flex` |
| Ark Seedance 1.0 Pro / Fast | 2-12 秒；480p/720p/1080p；不支持音频；参考图上限为 0 | 不适合依赖多参考图的视频流程；最终视频如需要音频应提示不支持 |
| OpenAI Sora | 4/8/12 秒；720p/1080p；参考图上限约 1 | 实际镜头时长不在 4/8/12 时应自动收敛或提示；不能传多参考图 |
| Grok Video | 1-15 秒；480p/720p；注册表未声明 1080p | 只能用于草稿或低规格输出；不适合作为 1080p 最终 profile |
| Vidu Q3 Turbo | 1-16 秒；540p/720p/1080p；支持音频、seed、参考图 | 草稿/最终可适配，但要按 endpoint 校验 duration |
| Vidu Q3 Pro | 1-16 秒；540p/720p/1080p；注册表声明参考图上限为 0 | 可用于非参考图/部分 endpoint；不应默认用于多参考图 reference2video |
| Vidu Q3 Reference | 3-16 秒；540p/720p/1080p；偏参考图流程 | 适合参考图视频，但不适合作为纯 T2V 默认 |
| Vidu 2.0 | 4/8 秒；360p/720p/1080p；I2V | 实际镜头时长不在 4/8 时应自动收敛或提示 |
| NewAPI video | 当前 endpoint 声明参考图上限 0，但 backend 可传 start_image，具体取决于中转站 | 只能作为保守兼容路线；最终版需要用户确认中转模型真实能力 |
| V2 video generations | 通用中转；支持公共子集，默认参考图上限保守为 4 | 适合自定义高级用户；必须把“不确定能力”展示为警告 |
| 自定义 `ark-seedance` | 复用 Ark 后端，但 model_id 命名可能是官方版或 Agent Plan 版 | endpoint 能力函数必须覆盖 Seedance 1.5/2.0/1.0 的所有命名，否则参考图/音频/service_tier 会错判 |
| 自定义 `vidu-video` | 复用 Vidu 后端，实际能力强依赖 model + endpoint | 不能只返回统一 max_reference=7；需要按 q3-pro/q3/q2/2.0 和 endpoint 精确判断 |

视频适配的关键是：先决定生成形态，再校验模型。

```text
是否有 start_image
是否有 end_image
是否有 reference_images
  -> 决定 endpoint / 请求形态
  -> 再校验 model 是否支持该 endpoint
  -> 再校验 duration / resolution / audio / seed / service_tier
```

不能只用 provider/model 的粗粒度 `supported_durations`，因为像 Vidu 这类供应商的合法时长是按 endpoint 变化的。

### 供应商输入图适配

输入图优化也必须按供应商和 endpoint 适配。不能统一把所有图都转成 JPEG，也不能统一把所有原图无损上传。

| 供应商/endpoint | 输入图适配要求 | 审查结论 |
| --- | --- | --- |
| OpenAI 图片 T2I | 不需要输入图 | 只需记录输出 size/quality；不走输入图准备层 |
| OpenAI 图片 I2I | 支持多参考图，后端会打开文件上传 | 需要真实 MIME；参考图数量超过上限要截断并记录；透明图/线稿优先保留 PNG |
| OpenAI Sora / openai-video | 通常参考图上限低，size 由分辨率和画幅映射 | 视频输入图建议 JPEG 2048px；多参考图必须按能力截断；未知 size 不应盲传 |
| Gemini Image | contents 可带参考图，`image_config` 控制画幅和尺寸 | 可用优化图，但要保留细节；母版不覆盖；MIME 要和真实文件一致 |
| Gemini Veo | 支持首帧/参考图能力有限，部分模型有 1080p/时长限制 | 输入图需按模型参考图上限准备；1080p 最终版要同时校验时长约束 |
| Ark Seedream | 图片请求用 `image` 和 `size`，不显式 size 可能丢画幅 | 输入图可优化，但 size 必须由 profile + aspect 解析；不能因压缩改变母版 |
| Ark Seedance | 支持 start/end/reference 角色，部分模型支持音频/seed/flex | 要按模型能力决定首帧、尾帧、reference_images；Seedance 2.0 不传 flex；大参考图先压缩 |
| Grok Image | T2I/I2I，常见 1K/2K | 可走通用图片输入优化；最终不能要求 4K |
| Grok Video | 最高常见 720p，支持参考图但不适合 1080p final | 主要用于草稿/低规格；输入图压到 720p/2048px 内即可，不能作为 1080p 终版默认 |
| Vidu Image | `/reference2image`，q1/q2 能力不同 | q1 必须有参考图，q2 可 T2I/I2I；分辨率/画幅走白名单；输入图数量 1-7 |
| Vidu Video | endpoint 随 start/end/reference 自动变化 | 必须先选 endpoint 再校验模型、时长、分辨率、参考图数量；reference2video prompt 上限更低 |
| NewAPI video | 中转兼容层，参考图能力不稳定 | 默认保守，不传多参考图；输入图大小要提前压缩和预估请求体 |
| V2 video generations | 通用中转，公共子集支持 image_url / image_urls / seed / resolution | 能力未知时只做 best effort；超过 4 张参考图默认截断或合成关键帧 |
| 自定义 OpenAI 图片类 | 取决于 `openai-images` / `generations` / `edits` endpoint | endpoint 决定 T2I/I2I 能力；自定义模型应允许配置真实分辨率和输入图限制 |
| 自定义视频类 | 取决于 `openai-video` / `newapi-video` / `v2` / `ark-seedance` / `vidu-video` | 必须以 endpoint registry + model 配置 + backend 能力三者共同判断，不能只看模型名 |

输入图适配必须返回可追踪 metadata：

```json
{
  "input_image_original_path": "storyboards/scene_1.png",
  "input_image_prepared_path": "tmp/provider-input/scene_1_2048.jpg",
  "input_image_original_mime": "image/png",
  "input_image_prepared_mime": "image/jpeg",
  "input_image_original_bytes": 5242880,
  "input_image_prepared_bytes": 820000,
  "input_image_transcoded": true,
  "input_image_max_long_edge": 2048,
  "input_image_jpeg_quality": 90
}
```

这份 metadata 应进入任务日志和版本 metadata。否则后续无法判断请求体变小、失败率下降、视频质量变化到底和哪一次输入图处理有关。

### 当前需要特别防守的适配风险

1. **自定义供应商分辨率选项过宽**
   当前前端对自定义图片/视频模型主要按 endpoint media type 给标准分辨率列表，例如图片给 `512px/1K/2K/4K`，视频给 `480p/720p/1080p/4K`。这可能展示模型并不支持的选项。最终应改为：

   ```text
   自定义模型显式 resolutions
     -> endpoint 默认候选
     -> 后端能力校验
   ```

2. **视频能力返回字段不足**
   当前视频能力主要返回时长和参考图数量。草稿/最终版还需要返回分辨率、分辨率与时长约束、音频、seed、service_tier、endpoint_family。

3. **Ark Seedance 自定义 endpoint 要覆盖 1.5 模型**
   内置注册表声明 Seedance 1.5 Pro 支持参考图上限 9，但自定义 `ark-seedance` 若只按后端 `video_capabilities_for_model()` 推断，必须确认它覆盖 `seedance-1.5` / `seedance-1-5` / Agent Plan 命名，否则自定义中转会和内置能力不一致。

4. **Vidu 的 registry 能力和 backend endpoint 能力要对齐**
   Vidu 的 q3-pro、q3、q2、2.0 在不同 endpoint 下能力不同。不能用一个统一 `max_reference_images=7` 代表所有 Vidu 模型，也不能只用 registry 的粗粒度时长代表所有 endpoint。

5. **文本结构化输出要单独校验**
   创建角色集、场景集、道具集、分镜脚本依赖结构化结果。文本供应商选择页应提示哪些模型适合 schema 输出，运行时也要有解析失败后的修复或重试策略。

6. **最终视频不能只看分辨率**
   最终版除了 1080p，还要看时长、音频、来源分镜版本、供应商参考图能力。比如 Sora 的 6 秒不适配，Grok 没有 1080p，Veo AI Studio 的 1080p 可能只允许 8 秒。

7. **输入图优化不能破坏母版**
   临时优化图只用于供应商请求。角色/场景/道具母版、分镜原图和用户上传原图不能被覆盖，否则版本回滚和高质量最终化都会失去依据。

8. **MIME 不能按后缀推断**
   当前项目存在 `.png` 路径里实际写入 JPEG 内容的情况。后续上传供应商时必须按文件头识别真实 MIME，否则可能造成供应商解析失败或质量异常。

9. **视频 prompt 精简不能丢失审计信息**
   传给视频模型的 prompt 应该精简，但完整分镜描述、精简规则和最终 motion prompt 都要记录。否则生成失败时无法判断是提示词过短还是模型能力不足。

10. **参考图截断必须可解释**
    如果因供应商上限截断参考图，任务结果需要记录“原始参考图数量、实际提交数量、截断原因”。不能静默丢图，否则用户会误以为模型没有服从参考。
    对 `reference_video` 而言，截断后的提交数量不能为 0；不支持参考图的模型必须在项目设置 route preview 和执行期阻断。

## 适配验收清单

实现时建议为每个供应商至少准备一组 dry-run 级验收，不真实扣费也要验证解析结果。

### 图片验收

```text
OpenAI GPT Image：1K 草稿、2K 最终、T2I/I2I 都能解析
Gemini Image：1K/2K/4K 能解析，aspect_ratio 正确传入
Ark Seedream：不传 size 时不会丢项目画幅；显式 profile resolution 能覆盖
Vidu q1：T2I 被阻止，I2I 可用
Vidu q2：T2I/I2I 可用，resolution 白名单生效
自定义 generations-only：只能进 T2I 槽
自定义 edits-only：只能进 I2I 槽
```

### 视频验收

```text
Veo：1080p + 6 秒若不支持，应提示或自动换合法时长
Seedance 1.5：720p 草稿 + 实际镜头时长、1080p/正式时长最终、service_tier 仅 flex 模型传
Seedance 2.0：不传 flex service_tier
Sora：6 秒被阻止或映射到 4/8/12
Grok：不能作为 1080p 最终 profile
Vidu q3/q2/2.0：按 endpoint 校验 duration 和 reference images
NewAPI：多参考图不可用时不传 reference_images
V2：未知能力以警告展示，不假装完全支持
```

### 智能体验收

```text
generate_assets 默认 final
generate_storyboards 默认 draft
generate_video_* 默认 draft
智能体请求 final 时会触发最终 profile
工具返回实际 provider/model/resolution/duration/quality
能力不足时智能体能解释原因，而不是只返回生成失败
```

### 稳定性与成本验收

```text
真实 MIME 类型与供应商日志一致
视频输入图不会覆盖原始母版
视频输入图有原始大小、优化后大小、是否转码记录
视频输入图 metadata 写入任务日志和版本 metadata
请求体过大 / 上传失败次数下降
同一镜头重试次数下降
单镜头平均生成成本下降
图生视频成功率提升
角色一致性人工评分提升
动作自然度人工评分提升
老项目素材不被覆盖，版本可回滚
视频 motion prompt 比完整分镜描述更短，且保留完整原文可回溯
参考图被截断时记录原始数量、实际提交数量和截断原因
临时输入图任务结束后可清理，失败任务可保留诊断信息
```

## 分阶段实施建议

### 第一阶段：不改变用户体验的稳定性改造

- 新增真实图片类型检测，不只依赖后缀。
- 新增 `prepare_provider_image_input(...)`。
- 为视频供应商输入图增加临时压缩层。
- 保留原始母版，不覆盖源文件。
- 在任务日志记录原图大小、输入图大小、MIME、是否压缩。
- 对 Vidu / NewAPI / V2 等请求体敏感供应商提前检查 Base64 后大小。
- 视频 prompt 进入供应商前提炼为动作、镜头、情绪、环境运动、禁止项，减少重复静态描述。

### 第二阶段：数据结构与后端解析

- 新增 `generation_profiles`
- 保持旧 `model_settings` 兼容
- 新增生成请求参数
- 新增 `generation_route_resolver`
- 写入版本 metadata
- 扩展视频能力返回字段
- 为 `generation_route_resolver` 接入供应商输入图准备层，确保路由、能力、输入图策略一致。
- 将 `grid` 从 `storyboard_draft/final` 拆出为独立 profile，默认跟随项目图片规格。
- 将 `reference_video` 接入独立 `reference_video_draft/final` 视频 profile。

### 第三阶段：前端单次生成

- 创建项目增加生成质量策略默认值（已完成：默认路径自动生成；高级区可在创建时编辑完整 profile）
- 项目设置展示和编辑 draft/final profile
- 资产默认生成母版
- 分镜支持草稿/最终版
- 宫格模式隐藏单分镜草稿/最终版，改为“生成宫格镜头板”
- 视频支持草稿/最终版
- 参考生视频支持草稿/最终版
- 版本面板显示质量、分辨率、供应商、模型
- 分镜/视频卡片展示当前素材是否使用优化输入图、是否基于最终分镜（已完成：从当前版本元数据展示徽标）

### 第四阶段：智能体工具

- `generate_assets` 默认 final
- `generate_storyboards` 默认 draft
- `generate_grid` 不提供低清草稿，默认 profile=grid
- `generate_video_*` 默认 draft
- `generate_video_*` 在 reference_video 模式下也要把 quality 传入 unit 任务
- 工具返回实际生成参数
- 能力查询工具返回 draft/final 推荐参数（已完成：`get_video_capabilities` 返回 `agent_generation_defaults` 与 `quality_recommendations.video/reference_video.draft/final`）
- 智能体生成视频时默认使用精简后的视频 motion prompt。（已完成：agent 入队透传结构化 `video_prompt`，执行层统一用 `_normalize_video_prompt` 转为 Action / Camera_Motion / Subject_Motion / Environment_Motion / Dialogue 等 motion prompt，并按供应商能力启用 compact policy）

### 第五阶段：镜头档位与质量闭环

- 增加镜头档位：S / A / B。（已完成：脚本模型支持 `shot_tier`，WebUI 分镜详情可切换 S/A/B，agent 字段编辑可写入 `shot_tier`）
- 不同档位绑定不同图片模型、视频模型、分辨率、重试次数。（已完成：`shot_tier_profiles` 可保存 profile 覆盖、参考图策略、重试预算和最终分镜来源偏好）
- 给项目配置默认策略，允许单镜头覆盖。（已完成：项目设置保存默认策略，脚本 item 的 `shot_tier` 作为单镜头覆盖进入任务 payload）
- 对首帧、首尾帧、多参考图分别记录成本和成功率。（已完成：用量统计按 provider/model/类型记录成功率，版本 metadata 记录来源分镜和参考图提交策略）
- 记录每次生成结果的人工评分。（已完成：分镜/视频卡片可保存总体评分与维度评分）
- 统计不同供应商在角色一致性、动作自然度、失败率上的表现。（已完成：质量统计返回维度平均值；供应商推荐返回历史成功率、失败次数、耗时和成本）
- 将历史成功率纳入默认模型推荐。（已完成：项目设置读取 `/usage/provider-recommendations` 并可一键应用推荐视频模型）
- 对失败类型分类：审核失败、请求体过大、角色漂移、动作错误、下载失败、超时。（已完成：worker 和最终化报告按失败类型分类并给出重试建议）

### 第六阶段：最终化与导出检查

- 新增“最终化本集”（已完成：剪映导出表单中可一键提交当前集最终化）
- 批量生成最终分镜（已完成：缺失 / 非最终分镜提交 `quality=final`，并透传 `shot_tier`；宫格生视频的 `grid` 来源不再要求单格最终化）
- 批量生成最终视频（已完成：缺失 / 非最终 / 基于草稿分镜 / 明确低规格视频提交 `quality=final`，并透传 `shot_tier`）
- 导出前检查草稿混入（已完成：拦截草稿视频、基于草稿分镜的视频、明确低规格视频）
- 输出最终化报告（已完成：提交后返回已入队任务和 issue 统计；任务完成后可查询失败分类和重试建议报告）

## 不建议的做法

- 不建议只把项目创建默认改成图片 2K、视频 1080p。
- 不建议只把项目创建默认改成图片 1K、视频 720p。
- 不建议让用户为了某个镜头反复修改项目设置。
- 不建议让最终成片混用 720p 和 1080p 视频。
- 不建议低规格满意后只改分辨率重新生成，因为这仍可能重新抽卡。
- 不建议只改 Web 前端按钮而不改智能体工具。
- 不建议把供应商能力写死在前端，应以后端能力解析为准。
- 不建议为了降低上传体积直接覆盖母版图。
- 不建议视频 prompt 重复塞入完整角色、服装、场景、道具静态描述。
- 不建议把所有参考图直接塞给视频模型；超过 3 张参考图应优先合成干净关键帧。
- 不建议只看 PNG/JPEG 文件后缀判断 MIME，应读取真实文件头。

## 参考资料

以下参考资料来自原 `docs/manju漫剧短剧图片视频生成方案.md`，用于后续实现时复核供应商最佳实践和计费规则：

- ArcReel：<https://arc-reel.com/en/>
- Cutflow：<https://www.cutflow.so/en>
- OpenAI Pricing：<https://platform.openai.com/docs/pricing/>
- OpenAI Image Generation：<https://platform.openai.com/docs/guides/image-generation>
- OpenAI Video Generation：<https://platform.openai.com/docs/guides/video-generation>
- Google Vertex AI Veo Best Practices：<https://cloud.google.com/vertex-ai/generative-ai/docs/video/best-practice>
- Google Vertex AI first / last frame video：<https://cloud.google.com/vertex-ai/generative-ai/docs/video/generate-videos-from-first-and-last-frames>
- Vidu Image-to-Video：<https://platform.vidu.com/docs/image-to-video/>
- Vidu Pricing：<https://platform.vidu.com/docs/pricing>
- xAI Image Generation：<https://docs.x.ai/docs/guides/image-generation>
- xAI Video Generation：<https://docs.x.ai/docs/guides/video-generations>

## 最终用户心智

用户不需要理解所有供应商参数，只需要理解：

```text
母版：角色/场景/道具的稳定参考源
草稿：便宜、快、用于试镜头
最终版：用于导出，规格统一
```

系统负责把这三类生成意图落到正确的供应商、模型、分辨率、时长、音频、输入图优化和版本记录上。
