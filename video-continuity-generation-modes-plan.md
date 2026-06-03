# Manju 分集分镜视频连续性生成方案

状态：实施草案 v0.6  
用途：记录三种生成视频模式的最终定位、已落地策略与剩余真实供应商压测项；当前本地可落地能力已完成。  
创建时间：2026-06-02

## 结论先行

Manju 后续最适合采用 **分镜优先 + 智能首尾帧 + 剪辑式过渡** 的生成策略。

不要把三种创建项目模式都做成同一种视频生成逻辑。推荐把它们明确拆成：

```text
图生视频（推荐）：正式成片主流程，最适合稳定控制每个分镜视频。
宫格分镜草稿：快速批量出分镜草稿，适合先看整体画风和节奏，最终视频回到逐镜头图生视频。
参考视频预览：参考图直出片段，适合快速预览和氛围短片，不作为逐分镜稳定衔接的默认方案。
```

当前主流 AI 视频制作流程已经越来越接近传统影视生产：

```text
角色 / 场景 / 道具资产
-> 分镜图 / 关键帧
-> 单镜头图生视频
-> 首尾帧或参考图控制连续性
-> 剪辑拼接与转场
```

也就是说，稳定漫剧不应该依赖“一条长 prompt 生成整集”，而应该依赖一套可追溯、可重试、可剪辑的镜头生产链路。

## 当前 Manju 现状

### 已有模式

当前项目创建支持三种 `generation_mode`：

```text
storyboard        图生视频（推荐）
grid              宫格分镜草稿
reference_video   参考视频预览
```

项目默认模式是 `storyboard`。已创建项目中的生成模式是固定项目结构，项目设置和分集都不支持切换；如需换模式，创建新项目。

### 当前图生视频链路

v0.3 之前，普通分镜视频生成大致是：

```text
当前分镜图 -> start_image
视频提示词 -> prompt
生成视频
```

v0.3 起，普通分镜视频任务已进入保守 `auto` 策略：

```text
当前分镜图 -> start_image
下一张分镜图 -> end_image，仅当模型真实支持 last_frame/end_image 且镜头关系适合连续过渡
视频提示词 -> prompt
生成视频
```

如果下一张分镜缺失、转场为 fade/dissolve、下一镜头是分段断点、或场景明显变化，后端会自动降级为 `start_only` 并写入版本 metadata。

### 当前分镜图链路

分镜图生成时已经会利用较多上下文：

- 角色图。
- 场景图。
- 道具图。
- 额外参考图。
- 上一张分镜图。
- S / A / B 镜头档位对应的参考图策略。

这意味着当前 Manju 的一致性主要依赖“分镜图先保持一致”，视频阶段则主要靠当前分镜图作为首帧。

### 当前视频生成器能力

后端 `MediaGenerator.generate_video_async` 已经具备以下输入概念：

- `start_image`：首帧图。
- `end_image`：尾帧图。
- `reference_images`：参考图列表。

并且已经会根据视频后端能力做处理：

```text
支持 last_frame：end_image 作为真实尾帧。
不支持 last_frame：默认不把 end_image fallback 成 reference_images。
只有显式 reference_assisted 策略才允许把下一张分镜作为参考图提交。
```

但对漫剧连续性来说，**不建议把“下一张分镜图”无脑 fallback 成参考图**。尾帧控制和参考图辅助不是同一种能力，产品上必须区分。

## 推荐产品定位

### 1. 图生视频模式：正式成片主流程

图生视频应成为 Manju 的默认推荐模式。

推荐定位：

```text
先生成完整分集的全部分镜图。
再逐镜头生成视频。
支持首尾帧的模型使用“当前分镜图 -> 下一分镜图”的首尾帧控制。
不支持首尾帧的模型只走当前分镜图首帧。
最后通过剪辑规则完成镜头切换。
```

正式视频生成时，第 N 个分镜视频的理想输入是：

```text
start_image = 第 N 张分镜图
end_image   = 第 N+1 张分镜图，仅当模型支持真实尾帧且两镜头适合连续过渡
prompt      = 当前镜头的动作、镜头运动、对白、情绪、环境运动
```

最后一个分镜没有下一张分镜图时，不传 `end_image`。

### 2. 宫格分镜草稿模式：快速草稿 / 批量分镜流程

宫格模式适合：

- 快速生成大量镜头候选。
- 统一画风。
- 降低前期试错成本。
- 先看一集的大体节奏。

宫格模式不适合作为最终视频连续性的主流程。推荐让宫格模式输出可以继续进入正式图生视频流程：

```text
宫格图
-> 切分单格分镜图
-> 作为普通分镜图进入图生视频
-> 支持首尾帧的模型再用下一张分镜图做 end_image
```

也就是说，宫格是“批量生成分镜图”的高效入口，不应该替代最终逐镜头视频生成。

### 3. 参考视频预览模式：参考直出 / 氛围片段流程

参考视频预览适合：

- 用角色、场景、道具参考图直接生成一段视频。
- 生成多镜头预览。
- 快速验证剧情氛围。
- 低控制成本地生成片段。

但它不适合承诺逐分镜的稳定衔接，因为它跳过了“每个分镜图都是明确关键帧”的环节。

推荐定位：

```text
参考视频预览 = 快速片段 / 氛围预览 / 辅助生产
图生视频 = 正式逐分镜成片
```

## 供应商与模型能力分档

不同供应商的视频能力不能用一个逻辑硬套。推荐在后端和 UI 中抽象为三个连续性等级。

### A 档：真实首尾帧模型

能力定义：

```text
支持 start_image。
支持 end_image / last_frame。
模型会尝试让视频从首帧过渡到尾帧。
```

推荐策略：

```text
同一场景、连续动作、人物关系稳定时：
  start_image = 当前分镜图
  end_image   = 下一张分镜图

换场、强跳切、人物/构图差异过大时：
  只传 start_image
  由剪辑层做硬切或淡入淡出
```

当前可优先纳入该档讨论的模型类型：

- Google Gemini / Veo 3.1 系列支持首尾帧生成。
- BytePlus / Ark Seedance 中明确支持首尾帧的模型。
- Vidu start-end-to-video 类模型。
- 自定义 V2 视频接口中支持 `last_image_url` 的模型。

### B 档：参考图辅助模型

能力定义：

```text
支持 start_image 或 reference_images。
不支持真实 end_image / last_frame。
```

推荐策略：

```text
普通正式分镜视频默认不要自动把下一张分镜图当 reference_image。
如要使用，必须在策略里标注为“参考辅助”，不能承诺尾帧准确落点。
```

原因：

- 参考图只是影响风格、角色、画面元素，不等于控制视频最终帧。
- 某些模型参考图数量有限，把下一分镜塞进去可能挤掉角色或场景参考。
- 某些模型只有 1 张参考图额度，强塞下一张分镜可能反而破坏首帧稳定。

适用场景：

- 参考视频预览。
- 氛围草稿。
- 某些模型经真实测试证明“下一分镜作为参考图”能提升连续性的特定场景。

### C 档：仅首帧模型

能力定义：

```text
只支持 start_image，或虽有图片输入但不适合做尾帧控制。
```

推荐策略：

```text
只传当前分镜图。
依赖分镜图一致性、prompt、剪辑转场保证成片观感。
```

这类模型仍可用于低成本草稿，但不应被 UI 描述为“支持平滑过渡”。

## 连续性策略

建议新增一个项目级策略字段：

```text
video_continuity_policy:
  auto                 智能连续性，默认
  start_only           仅首帧
  end_frame            使用真实尾帧
  reference_assisted   参考图辅助
```

### auto 策略

`auto` 是面向普通用户的默认策略。

后端根据模型能力和镜头关系自动判断：

```text
模型支持 last_frame
并且存在下一张分镜图
并且两镜头适合连续过渡
=> 使用 end_frame

否则
=> 使用 start_only
```

`reference_assisted` 不建议在普通图生视频里默认启用，但可以作为项目设置中的显式策略。启用后，只有模型真实支持 reference_images 且下一张分镜存在时，后端才会把下一张分镜作为参考图提交；它仍不承诺视频准确停在下一张分镜。

### 镜头关系判断

平滑过渡不是所有镜头的目标。影视语言中很多相邻镜头本来就应该硬切。

建议为每个分镜增加或推导一个字段：

```text
transition_to_next:
  cut          默认剪辑切换，可在同场景/非换段时使用 end_image
  fade         淡入淡出，不使用 end_image 或只作剪辑处理
  dissolve     叠化，不使用 end_image 或只作剪辑处理
```

自动判断可以先用简单规则：

```text
当前转场为 cut + 下一镜头不是 segment_break + 场景未明显变化 => 可使用 end_image
当前转场为 fade/dissolve => 不使用 end_image，交给剪辑层处理
下一镜头是 segment_break => 不使用 end_image
当前/下一镜头场景字段均存在且不重叠 => 不使用 end_image
```

最终采用的更稳分支是：**不让 LLM 直接自由输出 `transition_to_next`**。后端在脚本 metadata 补齐默认转场：普通相邻镜头为 `cut`，遇到下一镜头 `segment_break` 时把前一镜头默认设为 `fade`；用户可在分集分镜页手动覆盖。这样可以避免 LLM 误判转场污染视频生成请求，也更适配不同供应商模型。

### 2026-06-02 落地前复审修订

第一批实现采用保守边界：

```text
只在普通图生视频任务里启用 auto/end_frame。
只要模型真实支持 last_frame/end_image，才允许提交下一张分镜图。
不把下一张分镜图 fallback 成 reference_images。
暂不新增 continuous/scene_change 枚举，沿用当前 cut/fade/dissolve。
cut 是默认剪辑切换，不等于禁止首尾帧。
fade/dissolve 和下一镜头 segment_break 默认降级为 start_only。
```

供应商能力同步修订：

```text
Ark / Seedance 1.5 Pro 按 BytePlus 官方文档纳入真实首尾帧模型。
Vidu 不再把所有模型都视为支持首尾帧，必须按 start-end2video 端点白名单判断。
BytePlus / ModelArk 明确首帧、首尾帧、多模态参考是互斥场景，因此默认禁用 end_image -> reference_images fallback。
```

### 2026-06-02 第二批实施记录

已落地：

```text
普通分镜视频任务支持 auto/end_frame。
视频任务会在模型真实支持 last_frame/end_image 时，把下一张分镜图作为 end_image。
fade/dissolve、下一镜头 segment_break、明显换场、下一分镜缺失时自动降级为 start_only。
MediaGenerator 增加 allow_end_image_reference_fallback 开关，普通分镜视频默认禁用 end_image -> reference_images fallback。
视频版本 metadata 记录 video_continuity，便于追溯实际使用或降级原因。
Ark / Vidu 后端能力改为按模型判断首尾帧与参考图能力。
项目视频能力 API 增加 supports_start_image / supports_end_image / supports_reference_images / recommended_continuity_policy。
项目设置新增 video_continuity_policy，已创建项目可修改连续性策略但不能修改生成模式。
reference_assisted 作为显式策略已落地：模型支持参考图时可把下一张分镜作为 reference_images 提交。
前端模型配置优先消费后端 /video-capabilities 的真实能力，失败时才走本地启发式提示。
分集分镜页视频卡片展示连续性策略；已生成视频显示版本 metadata 中的实际策略，未生成视频显示预计策略。
```

当前边界 / 暂不默认：

```text
不把 reference_assisted 纳入 auto 默认路径，普通分镜视频默认仍不把下一张分镜当参考图。
不新增新的 transition enum，继续沿用 cut / fade / dissolve。
宫格和参考视频不承担正式逐镜头连续性主流程；UI 和文案明确定位为“宫格分镜草稿 / 参考视频预览”。
不新增视频任务硬依赖；当前策略是在入队前要求当前分镜图存在，执行时读取下一分镜图，缺失则降级并记录。
未做真实供应商逐模型回归压测；能力表仍需后续用小样本生成验证。
```

### 2026-06-02 第三批实施记录

已落地：

```text
创建项目默认显式写入 video_continuity_policy = auto。
创建项目默认显式写入 S / A / B shot_tier_profiles，三档 retry_budget 均为 1。
创建项目“生成质量策略”高级折叠中加入视频连续性策略选择，普通用户保持默认即可。
项目设置继续允许修改 video_continuity_policy，但生成模式保持锁定不可修改。
```

### 2026-06-02 第四批实施记录

已落地：

```text
三种模式 UI 文案收敛为：图生视频（推荐）/ 宫格分镜草稿 / 参考视频预览。
S / A / B 三档默认 retry_budget 全部为 1，避免用户无感知消耗更多 token。
S 档默认 full_context + auto 连续性 + 最终分镜 2K + 最终视频 1080p + 生成音频。
A 档默认 balanced + auto 连续性，作为普通正式镜头默认策略。
B 档默认 lean + start_only + 最终分镜 1K + 最终视频 720p + 不生成音频。
S / A / B 的 video_continuity_policy 会在视频任务中覆盖项目默认连续性策略。
分集分镜页增加每个分镜的转场控制，支持 cut / fade / dissolve 手动覆盖，并在提示中说明对 end_image 的影响。
脚本生成后由后端确定性补齐 transition_to_next，不把该字段交给 LLM 自由生成。
所有语言的三种模式文案同步到相同产品定位。
```

### 2026-06-02 第五批收口记录

已落地：

```text
创建项目时显式保存 generation_mode，非法模式由请求校验拦截。
项目 PATCH 继续禁止修改 generation_mode，episodes[] 也禁止写入 generation_mode。
前端有效模式只读取 project.generation_mode，删除未接入主界面的 EpisodeModeSwitcher 和对应文案。
草稿 step1 只按当前项目模式读写，不再跨模式 fallback 到旧文件。
reference_video 项目在仅存在 step1_reference_units.md、尚未生成 JSON 脚本时，状态可识别为 segmented。
分镜图被重新生成或宫格拆帧覆盖时，清空该分镜旧 video_clip / video_thumbnail / video_uri，让视频状态回到待重新生成。
```

## 三种模式的推荐生成流程

### 图生视频

推荐流程：

```text
1. 生成角色 / 场景 / 道具母资产。
2. 生成完整分集分镜脚本。
3. 生成所有分镜图。
4. 检查分镜图是否缺失或不合格。
5. 根据模型能力和 transition_to_next 生成每个分镜视频。
6. 拼接视频并应用硬切 / 淡入淡出 / 音频处理。
```

关键点：

- 视频任务不能在“下一张分镜图还没生成”时就使用 `end_image`。
- 如果启用首尾帧策略，第 N 个视频任务依赖第 N 和第 N+1 张分镜图。
- 分镜图质量直接决定视频质量，因此正式成片前应允许用户替换或重生成分镜图。

### 宫格分镜草稿

推荐流程：

```text
1. 根据分集段落批量生成宫格图。
2. 切分宫格为单张分镜图。
3. 用户挑选 / 替换 / 重生成不合格单格。
4. 进入普通图生视频流程。
```

关键点：

- 宫格本身偏“批量出图”，不是最终视频连续性策略。
- 宫格生成出来的单格也应进入版本管理。
- 如果单格质量不足，应允许单格重绘，而不是整宫格重来。

### 参考视频预览

推荐流程：

```text
1. 生成或选择角色 / 场景 / 道具参考图。
2. 生成 reference video unit。
3. 每个 unit 携带参考图和多镜头文本描述。
4. 调用支持参考图的视频模型。
5. 输出一段参考视频。
```

关键点：

- 参考视频预览可以更快，但镜头级可控性弱。
- 它适合草稿和预览，不适合作为逐分镜正式成片的默认模式。
- 如果用户最终要精细漫剧，参考视频可以反向拆解为分镜，再进入图生视频流程。

## S / A / B 档位建议

当前 S / A / B 不应主要表达“重试次数”，否则用户容易误以为只是更贵。

推荐让 S / A / B 表达生成质量策略：

```text
S：正式重点镜头，优先强模型、强连续性、更多参考上下文。
A：默认正式镜头，平衡质量和成本。
B：草稿或低成本镜头，少参考、首帧优先。
```

当前已落地的默认策略：

```text
S：
  retry_budget = 1
  reference_image_policy = full_context
  video_continuity_policy = auto
  prefer_final_storyboard_source = true
  storyboard_final.resolution = 2K
  video_final.resolution = 1080p
  video_final.generate_audio = true

A：
  retry_budget = 1
  reference_image_policy = balanced
  video_continuity_policy = auto
  prefer_final_storyboard_source = true

B：
  retry_budget = 1
  reference_image_policy = lean
  video_continuity_policy = start_only
  prefer_final_storyboard_source = false
  storyboard_final.resolution = 1K
  video_final.resolution = 720p
  video_final.generate_audio = false
```

也就是说，S / A / B 的差异不再来自隐藏增加重试次数，而来自：

- 模型档位。
- 分辨率。
- 是否启用首尾帧。
- 参考图策略。
- 是否生成音频。
- prompt 严格度。
- 是否进入最终视频合成。

## UI 建议

### 创建项目

创建项目时三种模式建议改成更明确的说明：

```text
图生视频（推荐）：先生成分镜图，再逐镜头生成视频，最适合稳定漫剧成片。
宫格分镜草稿：快速批量生成分镜草稿，适合低成本看整体画风和节奏；最终视频仍建议回到逐镜头生成。
参考视频预览：用角色/场景/道具参考图直接生成片段，适合快速预览和氛围草稿。
```

### 模型能力提示

视频模型选择处建议显示简短能力标签：

```text
支持首尾帧
支持参考图
仅首帧
支持音频
不支持音频
```

面向用户的提示应避免供应商术语过重：

```text
支持首尾帧：可让当前分镜视频自然过渡到下一张分镜图。
支持参考图：可参考角色/场景图，但不能保证视频停在下一张分镜。
仅首帧：从当前分镜图开始生成，镜头之间主要靠剪辑衔接。
```

### 分集分镜页

每个分镜视频生成按钮附近建议展示当前连续性策略：

```text
当前模型：支持首尾帧
本镜头：连续到下一镜头
将使用：当前分镜图 + 下一张分镜图
```

如果不支持首尾帧：

```text
当前模型仅支持首帧，将从当前分镜图生成视频；镜头衔接由剪辑处理。
```

## 后端实施方向

当前已按以下工程方向落地，后续只需结合真实供应商压测继续细化能力表。

### 1. 能力解析

基于现有 `VideoCapabilities` 明确输出：

```text
supports_start_image
supports_end_image
supports_reference_images
max_reference_images
supports_audio
recommended_continuity_policy
```

注意：

- `end_image` 只有在真实 `last_frame` 能力存在时才算支持。
- `reference_images` 不能等同于 `end_image`。
- 自定义供应商必须允许能力显式声明，否则只能走保守策略。

### 2. 视频任务依赖

使用 `end_image` 时，视频任务依赖关系变为：

```text
video[N] depends on storyboard[N] and storyboard[N+1]
```

因此最终视频批量生成顺序应改为：

```text
先确保所有分镜图存在
再创建视频任务
```

如果下一张分镜缺失：

```text
当前分镜视频降级为 start_only
并记录 metadata
```

### 3. 不默认 fallback 下一分镜为 reference

`MediaGenerator` 中保留了 `end_image -> reference_images` fallback 能力，但当前已经通过开关默认关闭：

```text
allow_end_image_reference_fallback = false
```

默认：

```text
支持 last_frame：传 end_image。
不支持 last_frame：不传 end_image。
```

只有在策略明确为 `reference_assisted` 时，才允许把下一张分镜作为参考图提交。

### 4. 版本 metadata

每个视频版本建议记录：

```json
{
  "video_continuity": {
    "requested_policy": "auto",
    "effective_policy": "end_frame",
    "start_storyboard_id": "E1S01",
    "end_storyboard_id": "E1S02",
    "transition_to_next": "cut",
    "provider_supports_end_image": true,
    "provider_supports_reference_images": true,
    "submitted_end_image": "..."
  }
}
```

这样后续用户看到某个视频衔接不好时，可以追溯到底是模型不支持，还是分镜差异太大，还是策略被降级。

## 推荐默认策略

### 新建项目默认

```text
generation_mode = storyboard
video_continuity_policy = auto
shot_tier = A
retry_budget = 1
```

新建项目当前会显式保存：

```text
video_continuity_policy = auto
shot_tier_profiles.S.retry_budget = 1
shot_tier_profiles.S.reference_image_policy = full_context
shot_tier_profiles.S.video_continuity_policy = auto
shot_tier_profiles.S.profiles.storyboard_final.resolution = 2K
shot_tier_profiles.S.profiles.video_final.resolution = 1080p
shot_tier_profiles.S.profiles.video_final.generate_audio = true
shot_tier_profiles.A.retry_budget = 1
shot_tier_profiles.A.reference_image_policy = balanced
shot_tier_profiles.A.video_continuity_policy = auto
shot_tier_profiles.B.retry_budget = 1
shot_tier_profiles.B.reference_image_policy = lean
shot_tier_profiles.B.video_continuity_policy = start_only
shot_tier_profiles.B.profiles.storyboard_final.resolution = 1K
shot_tier_profiles.B.profiles.video_final.resolution = 720p
shot_tier_profiles.B.profiles.video_final.generate_audio = false
```

### 正式成片默认

```text
如果模型支持真实首尾帧：
  同一连续镜头使用当前分镜 + 下一分镜。

如果模型不支持真实首尾帧：
  使用当前分镜首帧。
  UI 提示该模型不支持首尾帧连续性。
```

### 草稿默认

```text
低成本模型。
只使用 start_image。
不启用 end_image。
不做复杂参考图。
```

## 剩余待验证项

以下不属于本地代码未完成，而是需要真实供应商额度和样本生成才能确认：

1. 对 Ark / Seedance、Vidu、Kling、Veo 等首尾帧模型做小样本生成，分别测试“同场连续动作 / 换场 / 大角度变化 / 人物入出画”。
2. 验证 `reference_assisted` 在不同供应商上的真实收益，确认哪些模型适合把下一分镜作为参考图，哪些模型会被参考图干扰。
3. 记录每个模型的推荐 `video_continuity_policy`，必要时把能力表从“按模型家族”细化到“按具体模型版本”。
4. 后续可增强宫格草稿的单格重绘和批量挑选体验，但它不影响三种生成视频模式的核心定位。

## 外部参考

以下资料用于说明当前主流 AI 视频制作趋势和供应商能力方向，最终实现仍以后端真实能力解析和本地测试结果为准。

- [Runway Image to Video Prompting Guide](https://help.runwayml.com/hc/en-us/articles/48324313115155-Image-to-Video-Prompting-Guide)
- [Runway Gen-4 Image References](https://help.runwayml.com/hc/en-us/articles/40042718905875-Creating-with-Gen-4-Image-References)
- [Google Flow: AI-powered filmmaking with Veo](https://blog.google/innovation-and-ai/products/google-flow-veo-ai-filmmaking-tool/)
- [Google Gemini API Video generation / Veo](https://ai.google.dev/gemini-api/docs/video?authuser=6)
- [Google Vertex AI: Generate videos from first and last frames](https://cloud.google.com/vertex-ai/generative-ai/docs/video/generate-videos-from-first-and-last-frames)
- [Vidu API Start-End to Video](https://platform.vidu.com/docs/start-end-to-video)
- [Kling Video O1 User Guide](https://kling.ai/quickstart/klingai-video-o1-user-guide)
- [Kling AI Start and End Frames](https://kling.ai/quickstart/ai-video-start-end-frames)
- [Adobe Firefly: Create cinematic video from prompts and keyframes](https://www.adobe.com/learn/firefly/web/create-ai-video-with-text-prompts)
- [BytePlus ModelArk video generation docs](https://docs.byteplus.com/en/docs/modelark/1520757?utm_source=openai)
