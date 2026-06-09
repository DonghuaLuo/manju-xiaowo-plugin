---
name: compose-video
description: 把已生成的视频片段按剧本顺序拼接为单集成片，可选混入 BGM 与场景间转场。当用户说"拼成片"、"合成本集视频"或"加背景音乐"时使用。
---

# 合成视频

把单集已生成的视频片段按剧本顺序串接为一段成片，写入 `output/`。storyboard / grid 模式通常读取 `videos/*.mp4`，reference_video 模式通常读取 `reference_videos/*.mp4`。可选混入 BGM、按 `transition_to_next` 添加转场。

硬边界：本 skill **只合并现有视频片段**，不得调用任何视频生成工具，不得调用 `finalize`，不得把快速版视频自动重生为精修版。若任一场景 / 片段 / unit 缺少 `generated_assets.video_clip` 或文件不存在，必须提示缺失并停止。

## 适用范围（重要）

- **支持当前三种剧本结构** — drama 读取 `scenes[]`，narration 读取 `segments[]`，reference_video 读取 `video_units[]`
- **单集拼接** — 一次只处理一份剧本文件，不支持多集合并
- **不实现片头片尾 / BGM 音量调节** — 这些需求请走插件工作台的剪映草稿导出

## MCP 用法

合成固定调用 `mcp__arcreel__compose_video`。`script` 使用纯文件名：

```text
mcp__arcreel__compose_video({"script": "episode_1.json"})
mcp__arcreel__compose_video({"script": "episode_1.json", "music": "background_music.mp3"})
mcp__arcreel__compose_video({"script": "episode_1.json", "no_transitions": true})
mcp__arcreel__compose_video({"script": "episode_1.json", "output": "episode_1_merged.mp4"})
```

完整参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| `script` | 必填 | 剧本文件名，如 `episode_1.json` |
| `output` | 可选 | 输出文件名；缺省按剧本 `novel.chapter` 字段生成。无论何种取值，都会落在 `output/` 子目录内 |
| `music` | 可选 | BGM 文件路径（相对项目 cwd 或绝对路径），但**必须解析后位于项目目录内** |
| `no_transitions` | 可选 boolean | `true` 时全部用 cut 直接拼接，忽略剧本里的 `transition_to_next` |

## 工作流程

1. **读剧本** — 通过 `ProjectManager.load_script()` 从 `scripts/` 加载（路径过滤复用 lib 内 `_safe_subpath`）
2. **收集片段** — 按 `scenes[]` / `segments[]` / `video_units[]` 中的 `generated_assets.video_clip` 逐个解析视频文件并校验存在；缺任一片段立即停止
3. **拼接** — 默认走 normalize → concat（先把每段规范化为统一 H.264/AAC，再用 concat filter 编码），有 `xfade` 转场需求时按 `transition_to_next` 加滤镜
4. **混音** — 若指定 `--music`，再做一遍 audio mix；输出文件名追加 `_with_music`

## 支持的转场类型

按剧本字段 `transition_to_next` 映射；字段缺失时默认 `cut`：

| 字段值 | ffmpeg 行为 |
|---|---|
| `cut`（默认） | 直接拼接，无淡入淡出 |
| `fade` | `xfade=transition=fade:duration=0.5` |
| `dissolve` | `xfade=transition=dissolve:duration=0.5` |
| `wipe` | `xfade=transition=wipeleft:duration=0.5` |

## 前置检查

- [ ] 当前 cwd 是项目根（含 `project.json`）
- [ ] 剧本顶层有 `scenes[]`、`segments[]` 或 `video_units[]`
- [ ] 每个场景 / 片段 / unit 的 `generated_assets.video_clip` 都已生成，且文件存在
- [ ] `ffmpeg` / `ffprobe` 都在 PATH（脚本会预检）
- [ ] BGM 文件存在（如指定 `--music`）

## 限制 / 缺失能力

下列能力**未实现**，请使用插件工作台的剪映草稿导出：

- 多集合并 / 单集分片裁剪
- BGM 音量调节、独立 BGM 时间轴
- 片头片尾 intro/outro
- 字幕渲染
