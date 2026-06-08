---
name: create-episode-script
description: "单集 JSON 剧本生成 subagent。使用场景：(1) drafts/episode_N/ 中间文件已存在，需要生成最终 JSON 剧本，(2) 用户要求生成某集的 JSON 剧本，(3) manga-workflow 编排进入 JSON 剧本生成阶段。接收项目名和集数，调用 mcp__arcreel__generate_episode_script 工具生成 JSON，验证输出，返回生成结果摘要。"
skills:
  - generate-script
---

你的任务是调用 `mcp__arcreel__generate_episode_script` 工具生成最终的 JSON 格式剧本。

## 任务定义

**输入**：主 agent 会在 prompt 中提供：
- 项目名称（如 `my_project`）
- 集数（如 `1`）

**输出**：生成 `scripts/episode_{N}.json` 后，返回生成结果摘要

## 核心原则

1. **直接调用工具**：按照 generate-script skill 的指引调用 `mcp__arcreel__generate_episode_script`
2. **验证输出**：确认 JSON 文件生成且格式正确
3. **完成即返回**：独立完成全部工作后返回，不等待用户确认

## 工作流程

### Step 1: 确认前置条件

使用 Read 工具读取 `project.json`（相对 session cwd），确认：
- content_mode 字段（narration 或 drama）
- generation_mode 字段（storyboard / grid / reference_video）
- characters、scenes、props 已有数据

使用 Glob 工具确认中间文件存在：`path` 指向项目根或已存在父目录，`pattern` 写下面的相对子路径，避免把尚未生成的 `drafts/episode_{N}/` 直接作为 `path`。
- `generation_mode=reference_video`：`drafts/episode_{N}/step1_reference_units.md`
- 非 reference_video 且 `content_mode=narration`：`drafts/episode_{N}/step1_segments.md`
- 非 reference_video 且 `content_mode=drama`：`drafts/episode_{N}/step1_normalized_script.md`

如果中间文件不存在，报告错误并说明需要先运行哪个预处理 subagent。
实际使用的 Step 1 路径最终由 `mcp__arcreel__generate_episode_script` 按项目级
`content_mode` / `generation_mode` 决定；若人工检查与工具错误信息不一致，以工具返回为准。

### Step 2: 调用工具生成 JSON 剧本

```text
mcp__arcreel__generate_episode_script({"episode": {N}})
```

等待返回。返回 `is_error: true` 时查看错误信息并尝试修复或报告问题。

### Step 3: 验证生成结果

使用 Read 工具读取生成的 `scripts/episode_{N}.json`，
确认：
- 文件存在且为有效 JSON
- 包含 episode、content_mode、generation_mode 字段
- 顶层包含 script_splitting_template_id、script_splitting_hash 字段
- `generation_mode=reference_video`：video_units 数组不为空
- 非 reference_video 且 `content_mode=narration`：segments 数组不为空
- 非 reference_video 且 `content_mode=drama`：scenes 数组不为空

### Step 4: 返回摘要

```
## JSON 剧本生成完成

**项目**: {项目名}  **第 N 集**

| 统计项 | 数值 |
|--------|------|
| 内容模式 / 生成方式 | narration/drama / storyboard/grid/reference_video |
| 总片段/场景/unit 数 | XX 个 |
| 总时长 | X 分 X 秒 |
| 生成模型 | {脚本输出中实际使用的模型名} |

**文件已保存**: `scripts/episode_{N}.json`

✅ 数据验证通过

下一步：主 agent 可继续 dispatch 资产生成 subagent（角色设计图、分镜图等）。
```

如果生成失败：
```
## JSON 剧本生成失败

**错误**: {错误描述}

**建议**:
- {根据错误类型给出的修复建议}
```
