---
name: manage-project
description: 项目管理工具集。使用场景：(1) 分集切分——探测切分点并执行切分，(2) 查看 source 文本文件的安全统计信息，(3) 清理某集固定中间产物后重跑，(4) 新增/修改角色/场景/道具到 project.json（经 patch_project 工具，按 table+name upsert 或写顶层 settings 字段）。提供 MCP 版 peek（预览）+ split（执行）工作流、源文件统计、单集重置，以及角色/场景/道具与项目级 settings 写入。
user-invocable: false
---

# 项目管理工具集

提供项目文件管理工具，主要用于分集切分、单集重置和角色/场景/道具批量写入。

## 调用约束

- 项目源文件、JSON 剧本和固定中间产物只通过 MCP 工具处理。
- 源文件枚举、统计、切分点预览和分集写入固定调用 `mcp__arcreel__list_source_files` / `mcp__arcreel__source_info` / `mcp__arcreel__peek_split_point` / `mcp__arcreel__split_episode`。
- 重跑某集 JSON / 分镜时，调用 `mcp__arcreel__reset_episode_artifacts({"episode": N})` 清理固定产物；默认保留 `source/episode_N.txt`，避免后续误从 `_remaining.txt` 重新切错集。
- `source` 参数使用项目内相对路径，如 `source/原文.txt`、`source/_remaining.txt` 或 `source/episode_{N}.txt`；不要拼接项目绝对路径。
- 需要源文件行数、大小、字符数或阅读单位统计时，使用 `mcp__arcreel__source_info`。
- 如果目标集 `source/episode_{N}.txt` 不存在，先执行 MCP 版 peek/split 生成单集文件，不要用 Read/Grep 直接读取或搜索整本原文推进后续阶段。

## 工具一览

| 工具 | 功能 | 调用者 |
|------|------|--------|
| `mcp__arcreel__list_source_files` | 列出 source 文本文件，返回推荐源文件 | 主 agent（阶段 2） |
| `mcp__arcreel__source_info` | 输出 source 文本文件的行数、大小、字符数和阅读单位统计，不返回正文 | 主 agent / subagent |
| `mcp__arcreel__peek_split_point` | 探测目标字数附近的上下文和自然断点 | 主 agent（阶段 2） |
| `mcp__arcreel__split_episode` | 执行分集切分，生成 episode_N.txt + _remaining.txt | 主 agent（阶段 2） |
| `mcp__arcreel__reset_episode_artifacts` | 清理某集 JSON / 草稿等固定重跑产物，默认保留分集原文 | 主 agent / subagent |
| `mcp__arcreel__patch_project` | 新增/修改 project.json 的角色/场景/道具或顶层 settings 字段 | subagent / 主 agent |
| `mcp__arcreel__patch_episode_script` | 按分镜 id 编辑剧本字段 | subagent / 主 agent |
| `mcp__arcreel__insert_segment` | 插入分镜 | subagent / 主 agent |
| `mcp__arcreel__remove_segment` | 删除分镜 | subagent / 主 agent |
| `mcp__arcreel__split_segment` | 拆分分镜 | subagent / 主 agent |
| `mcp__arcreel__get_video_capabilities` | 查询当前项目视频模型能力 | subagent |

## 分集切分工作流

分集切分采用 **peek → 用户确认 → split** 的渐进式流程，由主 agent 在 manga-workflow 阶段 2 直接执行。

### 源文件统计

需要查看原文行数、文件大小、字符数或阅读单位时执行：

`mcp__arcreel__source_info({"source": "{源文件}"})`

输出 JSON 仅包含统计字段，不包含原文内容。`source` 使用 `source/原文.txt`、`source/_remaining.txt` 或 `source/episode_{N}.txt`，不要传项目绝对路径。

### Step 1: 探测切分点

`mcp__arcreel__peek_split_point({"source": "{源文件}", "target": 目标阅读单位})`

参数：

- `source`：源文件路径（`source/novel.txt` 或 `source/_remaining.txt`）
- `target`：目标阅读单位数（按 `source_language` 解读）
- `context`：上下文窗口大小（默认 200 字符）
- `language`：可选，覆盖 `project.json` 的 `source_language`（zh/en/vi）

输出 JSON：

- `language`：度量语言
- `total_units`：总阅读单位（zh 数汉字 + CJK 标点，en/vi 数 word）
- `target_units`：目标阅读单位
- `split_target_chars`：换算后的字符级 target，给 `mcp__arcreel__split_episode.target` 使用
- `target_offset`：目标对应的原文字符偏移
- `context_before` / `context_after`：切分点前后上下文
- `nearby_breakpoints`：附近自然断点列表

### Step 2: 执行切分

`mcp__arcreel__split_episode({"source": "{源文件}", "episode": N, "target": split_target_chars, "anchor": "{锚点文本}", "dry_run": true})`
`mcp__arcreel__split_episode({"source": "{源文件}", "episode": N, "target": split_target_chars, "anchor": "{锚点文本}"})`

注意：

- `split_episode.target` 是字符级目标，必须使用 peek 输出的 `split_target_chars`。
- 不要直接复用 peek 的 `target` 阅读单位值，否则英文/越南语或混排文本可能锚点搜索错位。

### 重跑清理

需要重新生成某一集的中间草稿和 JSON 剧本时，调用：

`mcp__arcreel__reset_episode_artifacts({"episode": N})`

该工具默认只删除固定路径：`scripts/episode_N.json`、`drafts/episode_N`，不会删除 `source/episode_N.txt`。
只有用户明确要重新切分原文，且你已经选定正确的原始源文件时，才传 `include_source: true`。

## 角色/场景/道具与 settings 写入

只能经 `mcp__arcreel__patch_project` 工具写入；项目名由 session 绑定，无需传参。

```text
mcp__arcreel__patch_project({"table": "characters", "entries": {"角色名": {"description": "...", "voice_style": "..."}}})
mcp__arcreel__patch_project({"table": "scenes", "entries": {"场景名": {"description": "..."}}})
mcp__arcreel__patch_project({"table": "props", "entries": {"道具名": {"description": "..."}}})
mcp__arcreel__patch_project({"settings": {"episode_target_units": 1000}})
mcp__arcreel__patch_project({"settings": {"source_language": "zh"}})
```

两种调用形态二选一：

- `{"table", "entries"}`：资产 upsert，按 table+name 新增或合并字段。
- `{"settings"}`：顶层字段写入。

settings 白名单字段：

- `episode_target_units`：`int >= 1` 设置 / `null` 清除。
- `source_language`：`"zh" / "en" / "vi"` 设置 / `null` 清除。

`project.json` 与 `scripts/*.json` 只能走 MCP 工具更新。

## 剧本编辑

`scripts/*.json` 的字段修改、分镜插入、删除、拆分只能走以下 MCP 工具：

- `mcp__arcreel__patch_episode_script`
- `mcp__arcreel__insert_segment`
- `mcp__arcreel__remove_segment`
- `mcp__arcreel__split_segment`

## 字数统计规则

- peek 的 `--target` 是阅读单位：zh 数汉字 + CJK 标点，en/vi 数 word。
- split 的 `--target` 是字符级非空白字符数。
- 空白字符在字符级统计中不计入。
