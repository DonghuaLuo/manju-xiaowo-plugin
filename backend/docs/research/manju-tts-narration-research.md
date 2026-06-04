# manju TTS 旁白调研摘要

日期：2026-06-04

本记录用于承接 ArcReel 的 TTS 路线调研，并按 manju 插件当前生成链路做收敛。

## 结论

- TTS 进入 manju 路线，但本次只同步架构决策，不在没有完整队列/前端/供应商契约时半实现运行时代码。
- audio 与 image/video 同属“按片段批量媒体生成”，应入 GenerationQueue。
- v1 可以优先支持同步 TTS API，例如 OpenAI 兼容 `/v1/audio/speech`、DashScope Qwen-TTS 同步接口；worker 层仍负责排队、并发和任务状态。
- 长文本或整集级 TTS 暂不作为 v1 默认形态；这类供应商常需要异步任务生命周期，应在 AudioBackend protocol 中预留。

## manju 适配注意

- 旁白音频应落入项目版本体系，后续剪映导出和成片合成读取同一版本来源。
- 角色音色、旁白音色与 `voice_style` 的关系需要在 UI 和 agent 工具层明确，不应只藏在 prompt 中。
- 成本统计要走 audio call_type 或 media_type，避免把 TTS 混入 text token 费用。
- audio lane 默认并发可比 video 更宽，但仍应与 image/video 分离，避免大量 TTS 阻塞视频生成。
