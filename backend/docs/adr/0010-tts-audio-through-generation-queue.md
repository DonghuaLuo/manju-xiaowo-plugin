---
status: proposed
date: 2026-06-04
---

# TTS 旁白音频走 GenerationQueue/Worker 路线

manju 后续接入 TTS（audio 媒体类型）时，采用与 image/video 一致的
GenerationQueue/Worker 路线，而不是跟 text 一样做同步内联调用。

核心判断不是“底层 TTS API 是否同步返回”，而是“生成基数和用户操作形态”。TTS 旁白通常按
segment/scene 批量生成，每集可能有 N 段，需要任务面板、进度、失败重试、取消和跨页面续看；
这些行为与分镜图、视频片段一致，而与“每集一次”的文本生成不同。

## 决策

- audio 增加独立 media_type，并作为队列任务入库。
- 单段 TTS = 入队一条 audio task；批量 TTS = 入队 N 条 audio task。
- Web 与 agent 工具都应走 enqueue 语义，复用现有 `/api/v1/tasks` 任务面板。
- v1 的 AudioBackend 可以是同步一次性实现：worker claim 后调用 backend，拿到音频字节后立即落版本并标终态。
- 若未来接入长文本/异步 TTS 供应商，再扩展 submit/poll/resume 生命周期；不把 v1 同步 backend 误等同为“audio 不入队”。

## 后续落地范围

- `ProviderPool` 增加 audio lane，例如 `audio_max` / `has_audio_room`。
- worker claim 循环从 image/video 扩展到 image/video/audio。
- 任务、版本、用量统计、取消/失败状态复用现有 GenerationQueue 契约。
- agent 工具命名倾向 `enqueue_tts`，参数支持缺失段、指定 segment_ids、单段重生。
- text 仍保持同步内联；若以后要让 text 入队，应另起 ADR 说明生成基数或交互形态已经变化。
