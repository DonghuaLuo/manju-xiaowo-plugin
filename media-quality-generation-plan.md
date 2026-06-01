# Manju 媒体质量分层生成方案

## 背景

当前项目创建中，图片和视频分辨率主要以项目级模型配置保存。生成角色、场景、道具、分镜、视频时，后端统一从项目配置解析分辨率。

这个方式适合简单默认值，但不适合小说自动生产流程。原因是：

- 角色、场景、道具会作为后续分镜参考图反复使用，它们是母资产，不应按草稿规格生成。
- 分镜和视频在创作阶段需要低成本快速试错。
- 最终成片不应该混入不同规格的视频，否则画面稳定性和观感会不一致。
- 如果低规格满意后只是改高分辨率重新生成，本质上仍可能是重新抽卡，画面、动作、细节可能走偏。

因此需要把“默认模型配置”升级为“媒体质量分层配置”。

## 当前生成链路

### 前端入口

主要入口在：

- `frontend/src/components/canvas/StudioCanvasRouter.tsx`
- `frontend/src/api.ts`

当前前端调用特点：

- 角色生成：只传 `prompt`
- 场景生成：只传 `prompt`
- 道具生成：只传 `prompt`
- 分镜生成：只传 `prompt`、`script_file`
- 视频生成：只传 `prompt`、`script_file`、`duration_seconds`

当前没有单次传入：

- `quality`
- `resolution`
- `seed`
- `source_version`
- `draft/final`

### 后端入口

主要入口在：

- `backend/server/routers/generate.py`
- `backend/server/services/generation_tasks.py`
- `backend/server/services/resolution_resolver.py`

当前后端调用特点：

- 所有生成请求先通过 `TaskSpec.from_request` 入队。
- 图片任务在执行阶段解析图片供应商。
- 视频任务在执行阶段解析视频供应商。
- 分辨率通过 `resolve_resolution(project, provider_id, model_id)` 解析。
- `resolve_resolution` 当前优先级为：

```text
project.model_settings
  -> legacy video_model_settings
  -> 自定义供应商模型默认 resolution
  -> None
```

当前没有按资源用途区分：

- 资产库图片
- 分镜草稿
- 分镜最终版
- 视频草稿
- 视频最终版

## 当前供应商调用关系

### 图片

图片供应商由 `ConfigResolver.resolve_image_backend()` 解析。

优先级：

```text
payload 覆盖
  -> 项目 image_provider_t2i / image_provider_i2i
  -> 全局默认图片供应商
```

如果配置为 GPT Image 2，则走 OpenAI 图片后端。

GPT Image 2 当前支持：

```text
512px
1K
2K
```

### 视频

视频供应商由 `ConfigResolver.resolve_video_backend()` 解析。

优先级：

```text
payload 覆盖
  -> 项目 video_backend
  -> 全局默认视频供应商
```

如果配置为 Doubao Seedance，则走 Ark/火山后端。

Seedance 当前支持：

```text
480p
720p
1080p
```

Seedance 2.0 / 2.0 Fast 当前支持 4-15 秒。

## 目标生成策略

整体策略：

```text
母资产高质量
草稿低成本
最终成片统一规格
```

推荐默认规格：

```text
资产库图片：2K
分镜草稿：1K
分镜最终版：2K
视频草稿：720p
视频最终版：1080p
默认时长：6 秒
```

## 推荐用户流程

```text
1. 上传小说
2. 自动分析角色、场景、道具
3. 生成角色/场景/道具母资产，默认 2K
4. 自动拆分分集和分镜
5. 生成分镜草稿，默认 1K
6. 生成视频草稿，默认 720p
7. 用户检查镜头、动作、角色一致性
8. 执行“最终化本集”
9. 生成最终分镜，默认 2K
10. 基于最终分镜生成最终视频，默认 1080p
11. 导出成片前检查是否仍有草稿视频
```

## 配置结构建议

在项目配置中新增 `quality_settings`。

示例：

```json
{
  "quality_settings": {
    "asset_image_resolution": "2K",
    "storyboard_draft_resolution": "1K",
    "storyboard_final_resolution": "2K",
    "video_draft_resolution": "720p",
    "video_final_resolution": "1080p"
  }
}
```

旧的 `model_settings` 继续保留，用于兼容已有项目和模型级默认分辨率。

建议新解析优先级：

```text
payload.resolution
  -> project.quality_settings 按 task_type + quality 解析
  -> project.model_settings
  -> legacy video_model_settings
  -> 自定义供应商模型默认 resolution
  -> None
```

## API 参数建议

图片和视频生成 API 增加可选参数：

```ts
type GenerationQuality = "draft" | "final";

interface GenerationOptions {
  quality?: GenerationQuality;
  resolution?: string;
  seed?: number;
  source_version?: number;
}
```

分镜生成请求：

```json
{
  "prompt": {},
  "script_file": "episode_1.json",
  "quality": "draft",
  "resolution": "1K",
  "seed": 123
}
```

视频生成请求：

```json
{
  "prompt": {},
  "script_file": "episode_1.json",
  "duration_seconds": 6,
  "quality": "final",
  "resolution": "1080p",
  "seed": 123,
  "source_version": 3
}
```

## 前端修改方案

### 项目创建 / 项目设置

把现有单一图片/视频分辨率文案调整为生产规格配置：

- 资产库图片规格
- 分镜草稿规格
- 分镜最终规格
- 视频草稿规格
- 视频最终规格

创建项目时可以默认填入推荐值。

### 资产库页面

角色、场景、道具生成按钮保持简单：

```text
生成母版
```

默认走：

```text
quality = final
resolution = asset_image_resolution
```

原因：角色、场景、道具会作为后续参考图反复使用，不建议低规格。

### 分镜卡片

分镜生成按钮建议拆为：

- 生成草稿
- 生成最终版

默认按钮可以是“生成草稿”，旁边提供下拉菜单。

行为：

```text
生成草稿 -> quality=draft, resolution=storyboard_draft_resolution
生成最终版 -> quality=final, resolution=storyboard_final_resolution
```

如果已有满意草稿图，最终版应优先基于当前图做图生图或高清化，而不是只用同一个 prompt 重新抽。

### 视频卡片

视频生成按钮建议拆为：

- 生成草稿
- 生成最终版

行为：

```text
生成草稿 -> quality=draft, resolution=video_draft_resolution
生成最终版 -> quality=final, resolution=video_final_resolution
```

生成最终视频前建议检查：

- 当前分镜图是否存在。
- 当前分镜图是否是最终规格。
- 如果不是最终规格，提示先生成最终分镜。

### 本集最终化入口

建议新增“最终化本集”动作。

逻辑：

```text
1. 扫描本集所有分镜
2. 检查角色/场景/道具母资产是否存在
3. 对缺少最终分镜的镜头生成最终分镜
4. 对缺少最终视频的镜头生成 1080p 视频
5. 输出最终化报告
```

报告示例：

```text
本集最终化完成
- 最终分镜：28/30
- 最终视频：30/30
- 仍需处理：2 个分镜生成失败
```

## 后端修改方案

### 请求模型

在 `GenerateStoryboardRequest`、`GenerateVideoRequest`、`GenerateCharacterRequest`、`GenerateSceneRequest`、`GeneratePropRequest` 中增加：

```py
quality: Literal["draft", "final"] | None = None
resolution: str | None = None
source_version: int | None = None
```

视频保留已有：

```py
duration_seconds: int | None = None
seed: int | None = None
```

### 入队 payload

`TaskSpec.from_request()` 已经支持 `extra_payload`，可以把新参数放入 payload：

```py
extra_payload={
    "quality": req.quality,
    "resolution": req.resolution,
    "seed": req.seed,
    "source_version": req.source_version,
}
```

注意应过滤 `None`，避免 payload 噪音。

### 分辨率解析

新增函数：

```py
async def resolve_generation_resolution(
    project: dict,
    provider_id: str,
    model_id: str,
    *,
    task_type: str,
    quality: str | None,
    payload: dict | None,
) -> str | None:
    ...
```

解析规则：

```text
1. payload.resolution
2. project.quality_settings[task_type + quality 对应 key]
3. resolve_resolution(project, provider_id, model_id)
```

建议映射：

```py
QUALITY_RESOLUTION_KEYS = {
    ("character", "final"): "asset_image_resolution",
    ("scene", "final"): "asset_image_resolution",
    ("prop", "final"): "asset_image_resolution",
    ("storyboard", "draft"): "storyboard_draft_resolution",
    ("storyboard", "final"): "storyboard_final_resolution",
    ("video", "draft"): "video_draft_resolution",
    ("video", "final"): "video_final_resolution",
}
```

### 执行任务

需要改这些执行函数：

- `execute_character_task`
- `execute_design_task`
- `execute_storyboard_task`
- `execute_video_task`

把当前：

```py
image_size = await resolve_resolution(project, provider_id, model_id)
```

改为：

```py
image_size = await resolve_generation_resolution(
    project,
    provider_id,
    model_id,
    task_type="storyboard",
    quality=payload.get("quality"),
    payload=payload,
)
```

视频同理。

### 版本记录

`MediaGenerator.generate_image_async()` 和 `generate_video_async()` 已经支持 `**version_metadata`。

建议每次生成都写入：

```json
{
  "quality": "draft",
  "resolution": "1K",
  "provider_id": "openai",
  "model": "gpt-image-2",
  "source_version": 2
}
```

视频额外写入：

```json
{
  "duration_seconds": 6,
  "seed": 123,
  "generate_audio": true
}
```

这样前端版本面板可以显示当前版本到底是草稿还是最终版。

## 导出前检查

导出成片前建议增加质量检查。

检查项：

- 是否存在缺视频镜头。
- 是否存在 `quality=draft` 的视频。
- 是否存在分辨率低于最终规格的视频。
- 是否存在引用的角色/场景/道具母资产缺失。

如果有问题，提示：

```text
当前项目仍有草稿视频或低规格资产，建议先执行“最终化本集”。
```

## 分阶段实施建议

### 第一阶段：后端协议和解析

- 增加 `quality_settings`
- 增加请求参数
- 增加任务级分辨率解析
- 版本记录写入 `quality / resolution / provider / model`
- 保持旧项目兼容

### 第二阶段：前端单次生成

- 资产生成默认母版规格
- 分镜按钮支持草稿/最终版
- 视频按钮支持草稿/最终版
- 版本面板展示质量标签和分辨率

### 第三阶段：最终化本集

- 新增最终化入口
- 批量检查缺失项
- 批量生成最终分镜和最终视频
- 导出前提示草稿混入风险

## 不建议的做法

- 不建议只把项目创建默认改成图片 2K、视频 1080p。
- 不建议让用户为了某个镜头反复修改项目设置。
- 不建议最终成片混用 720p 和 1080p 视频。
- 不建议低规格满意后只改分辨率重新生成，因为这仍可能重新抽卡。
- 不建议把每个资产都做成复杂永久配置面板，优先用“生成时质量模式”解决。

## 最终目标

用户不需要理解所有底层参数，只需要知道：

```text
草稿：便宜、快、用于试镜头
母版：角色/场景/道具的稳定参考源
最终版：用于导出，规格统一
```

系统负责把这三类生成规格落到正确的供应商参数上。
