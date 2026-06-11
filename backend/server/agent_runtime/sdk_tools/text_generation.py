"""SDK MCP tools for text generation (script + normalization) and capability queries.

`get_video_capabilities` ships in this module because it shares the same
`ConfigResolver.video_capabilities` plumbing as ``normalize_drama_script``;
keeping them together avoids a one-tool stub file.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool

from lib.config.resolver import ConfigResolver
from lib.db import async_session_factory
from lib.project_manager import effective_mode
from lib.prompt_builders_script import build_normalize_prompt
from lib.script_generator import ScriptGenerator
from lib.script_splitting_templates import current_profile, ensure_project_script_splitting_snapshot
from lib.text_backends.base import TextGenerationRequest, TextTaskType
from lib.text_generator import TextGenerator
from server.agent_runtime.sdk_tools._context import (
    ToolContext,
    auto_repair_tool_error,
    fetch_video_caps,
    tool_error,
    tool_result_text,
)
from server.services.generation_route_resolver import GenerationRoute, resolve_generation_route
from utils.agent_ops_autofix import auto_repair_runtime_failure, format_auto_repair_note

logger = logging.getLogger(__name__)

_FALLBACK_SUPPORTED_DURATIONS: list[int] = [4, 6, 8]
_MARKDOWN_FENCE_RE = re.compile(r"^\s*```(?:markdown|md)?\s*(.*?)\s*```\s*$", re.IGNORECASE | re.DOTALL)
_STEP1_ID_RE = re.compile(r"^E(?P<episode>\d+)S\d+(?:_\d+)?$")
_STEP1_EMPTY_VALUES = {"", "-", "无", "none", "null"}
_STEP1_HEADER_ALIASES = {
    "场景id": "scene_id",
    "场景编号": "scene_id",
    "分镜id": "scene_id",
    "分镜编号": "scene_id",
    "镜头id": "scene_id",
    "镜头编号": "scene_id",
    "场景描述": "scene_description",
    "分镜描述": "scene_description",
    "镜头描述": "scene_description",
    "描述": "scene_description",
    "时长": "duration_seconds",
    "duration": "duration_seconds",
    "segmentbreak": "segment_break",
}


def _strip_markdown_fence(text: str) -> str:
    stripped = str(text or "").strip()
    match = _MARKDOWN_FENCE_RE.match(stripped)
    return match.group(1).strip() if match else stripped


def _split_markdown_row(line: str) -> list[str]:
    stripped = line.strip()
    if "|" not in stripped:
        return []
    cells = [cell.strip() for cell in stripped.split("|")]
    if cells and cells[0] == "":
        cells = cells[1:]
    if cells and cells[-1] == "":
        cells = cells[:-1]
    return cells


def _is_markdown_separator(cells: list[str]) -> bool:
    return bool(cells) and all(bool(re.fullmatch(r":?-{3,}:?", cell.strip())) for cell in cells)


def _canonical_step1_header(cell: str) -> str:
    normalized = str(cell or "").strip().strip("`").lower().replace(" ", "")
    return _STEP1_HEADER_ALIASES.get(normalized, normalized)


def _profile_output_fields(profile: dict[str, Any]) -> list[str]:
    fields = [str(field) for field in profile.get("output_fields") or [] if str(field).strip()]
    return fields or ["scene_id", "scene_description", "duration_seconds", "segment_break"]


def _validate_normalized_drama_step1(
    markdown: str,
    *,
    episode: int,
    script_profile: dict[str, Any],
    supported_durations: list[int],
) -> int:
    if not markdown.strip():
        raise ValueError("normalize_drama_script 返回空内容，拒绝写入 Step 1")

    header: list[str] | None = None
    rows: list[dict[str, str]] = []
    for line in markdown.splitlines():
        cells = _split_markdown_row(line)
        if not cells:
            continue
        if header is None:
            normalized = [_canonical_step1_header(cell) for cell in cells]
            if "scene_id" not in normalized:
                continue
            header = normalized
            continue
        if _is_markdown_separator(cells):
            continue
        row = {field: cells[index].strip() if index < len(cells) else "" for index, field in enumerate(header)}
        if any(value.strip() for value in row.values()):
            rows.append(row)

    if header is None:
        raise ValueError("normalize_drama_script 未返回包含 scene_id/场景 ID 的 Markdown 表格")
    missing_fields = [field for field in _profile_output_fields(script_profile) if field not in header]
    if missing_fields:
        raise ValueError(f"normalize_drama_script 返回表格缺少列: {', '.join(missing_fields)}")
    if not rows:
        raise ValueError("normalize_drama_script 返回表格没有任何场景行")

    allowed_durations = {int(value) for value in supported_durations}
    seen_ids: set[str] = set()
    for index, row in enumerate(rows, start=1):
        scene_id = row.get("scene_id", "").strip().strip("`")
        match = _STEP1_ID_RE.fullmatch(scene_id)
        if match is None:
            raise ValueError(f"第 {index} 行 scene_id 无效: {scene_id!r}，应为 E{episode}S01 格式")
        if int(match.group("episode")) != int(episode):
            raise ValueError(f"第 {index} 行 scene_id 集号错误: {scene_id!r}，当前应为第 {episode} 集")
        if scene_id in seen_ids:
            raise ValueError(f"normalize_drama_script 返回重复 scene_id: {scene_id}")
        seen_ids.add(scene_id)

        raw_duration = row.get("duration_seconds", "").strip().lower().removesuffix("秒").removesuffix("s").strip()
        if raw_duration:
            try:
                duration = int(raw_duration)
            except ValueError as exc:
                raise ValueError(f"第 {index} 行 duration_seconds 不是整数: {row.get('duration_seconds')!r}") from exc
            if allowed_durations and duration not in allowed_durations:
                raise ValueError(
                    f"第 {index} 行 duration_seconds={duration} 不在模型支持集合 {sorted(allowed_durations)} 内"
                )

        segment_break = row.get("segment_break", "").strip().lower()
        if segment_break not in _STEP1_EMPTY_VALUES | {"是", "否", "true", "false", "yes", "no", "y", "n"}:
            raise ValueError(f"第 {index} 行 segment_break 值无效: {row.get('segment_break')!r}")

    return len(rows)


def _read_episode_source_text(project_path: Path, episode: int, source: Any) -> tuple[str, list[Path]]:
    if source:
        source_path = (project_path / str(source)).resolve()
        if not source_path.is_relative_to(project_path.resolve()):
            raise ValueError(f"路径超出项目目录: {source_path}")
        if not source_path.exists():
            raise FileNotFoundError(f"未找到源文件: {source_path}")
        return source_path.read_text(encoding="utf-8"), [source_path]

    source_dir = project_path / "source"
    if not source_dir.exists() or not any(source_dir.iterdir()):
        raise FileNotFoundError(f"source/ 目录为空或不存在: {source_dir}")

    suffixes = (".txt", ".md", ".text")
    episode_files = [
        source_dir / f"episode_{episode}{suffix}"
        for suffix in suffixes
        if (source_dir / f"episode_{episode}{suffix}").is_file()
    ]
    files = episode_files or [path for path in sorted(source_dir.iterdir()) if path.suffix in suffixes]
    return "\n\n".join(path.read_text(encoding="utf-8") for path in files), files


def _project_for_drama_normalization(project: dict[str, Any]) -> dict[str, Any]:
    project_for_prompt = dict(project)
    project_for_prompt["content_mode"] = "drama"
    snapshot = project_for_prompt.get("script_splitting")
    profile = snapshot.get("resolved_profile") if isinstance(snapshot, dict) else None
    if isinstance(profile, dict) and profile.get("content_mode") != "drama":
        project_for_prompt.pop("script_splitting", None)
        project_for_prompt.pop("script_splitting_template_id", None)
    return project_for_prompt


def _resolve_drama_script_profile(project_for_prompt: dict[str, Any]) -> dict[str, Any]:
    try:
        ensure_project_script_splitting_snapshot(project_for_prompt)
    except ValueError as exc:
        if "不能用于 drama 项目" not in str(exc):
            raise
        project_for_prompt.pop("script_splitting", None)
        project_for_prompt.pop("script_splitting_template_id", None)
        ensure_project_script_splitting_snapshot(project_for_prompt)
    return current_profile(project_for_prompt)


def _write_dry_run_prompt(project_path: Path, episode: int, name: str, prompt: str) -> Path:
    dry_run_dir = project_path / "drafts" / f"episode_{episode}"
    dry_run_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = dry_run_dir / f"{name}_prompt_dry_run.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    return prompt_path


def _dry_run_tool_result(title: str, prompt: str, prompt_path: Path) -> dict[str, Any]:
    text = f"{title}\n完整 prompt 已保存: {prompt_path}\nPrompt 长度: {len(prompt)} 字符\n\n{prompt}"
    return tool_result_text(text, label=f"{title} prompt", source_path=prompt_path)


def _episode_script_summary_text(result_path: Path) -> str:
    """Build a compact top-level summary so agents do not shell out for jq."""
    lines = [f"✅ 剧本生成完成: {result_path}"]
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - generation succeeded; summary is best-effort
        lines.append(f"⚠️  摘要读取失败，请用 Read 工具复核: {exc}")
        return "\n".join(lines)

    if not isinstance(payload, dict):
        lines.append(f"⚠️  摘要读取失败: 顶层 JSON 不是对象，而是 {type(payload).__name__}")
        return "\n".join(lines)

    metadata = payload.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    generator = metadata.get("generator") or payload.get("generator") or payload.get("model") or metadata.get("model")
    scenes = payload.get("scenes") if isinstance(payload.get("scenes"), list) else []
    segments = payload.get("segments") if isinstance(payload.get("segments"), list) else []
    video_units = payload.get("video_units") if isinstance(payload.get("video_units"), list) else []

    lines.extend(
        [
            f"episode: {payload.get('episode')}",
            f"content_mode: {payload.get('content_mode')}",
            f"generation_mode: {payload.get('generation_mode')}",
            f"script_splitting_template_id: {payload.get('script_splitting_template_id')}",
            f"script_splitting_hash: {payload.get('script_splitting_hash')}",
            f"duration_seconds: {payload.get('duration_seconds')}",
            f"scenes_count: {len(scenes)}",
            f"segments_count: {len(segments)}",
            f"video_units_count: {len(video_units)}",
            f"model: {generator or 'unknown'}",
            "提示: 顶层校验字段已在工具返回中提取，无需再调用 shell JSON 工具。",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# get_video_capabilities
# ---------------------------------------------------------------------------


async def _resolve_video_capabilities(project_name: str) -> dict[str, Any]:
    resolver = ConfigResolver(async_session_factory)
    return await resolver.video_capabilities(project_name)


def _route_recommendation(route: GenerationRoute) -> dict[str, Any]:
    return {
        "task_kind": route.task_kind,
        "quality": route.quality,
        "profile_key": route.profile_key,
        "provider_id": route.provider_id,
        "model": route.model_id,
        "resolution": route.resolution,
        "duration_seconds": route.duration_seconds,
        "generate_audio": route.generate_audio,
        "service_tier": route.service_tier,
        "seed": route.seed,
        "supported_resolutions": route.supported_resolutions,
        "supported_durations": route.supported_durations,
        "duration_resolution_constraints": route.duration_resolution_constraints,
        "warnings": route.warnings,
    }


async def _build_video_quality_recommendations(
    *,
    project_name: str,
    project: dict[str, Any],
) -> dict[str, dict[str, dict[str, Any]]]:
    resolver = ConfigResolver(async_session_factory)
    recommendations: dict[str, dict[str, dict[str, Any]]] = {}
    for task_kind in ("video", "reference_video"):
        task_recommendations: dict[str, dict[str, Any]] = {}
        for quality in ("draft", "final"):
            try:
                route = await resolve_generation_route(
                    project=project,
                    payload={},
                    task_kind=task_kind,
                    quality=quality,
                    resolver=resolver,
                    project_name=project_name,
                )
                task_recommendations[quality] = _route_recommendation(route)
            except Exception as exc:  # noqa: BLE001 - 能力查询应尽量返回其它可用档位
                task_recommendations[quality] = {"error": str(exc)}
        recommendations[task_kind] = task_recommendations
    return recommendations


def get_video_capabilities_tool(ctx: ToolContext):
    @tool(
        "get_video_capabilities",
        "查当前项目的视频模型能力（model 粒度）+ 用户项目偏好。返回 JSON。",
        {"type": "object", "properties": {}},
    )
    async def _handler(_args: dict[str, Any]) -> dict[str, Any]:
        try:
            project = ctx.pm.load_project(ctx.project_name)
            resolver = ConfigResolver(async_session_factory)
            payload = await resolver.video_capabilities_for_project(project)
            payload["agent_generation_defaults"] = {
                "assets": "final",
                "storyboards": "draft",
                "grid": "final",
                "videos": "draft",
                "reference_videos": "draft",
            }
            payload["quality_labels"] = {
                "draft": "快速版（批量/Agent 自动生成默认）",
                "final": "精修版（仅用户明确指定的单镜头精修）",
            }
            payload["agent_generation_policy"] = (
                "角色/场景/道具和宫格图默认走高质量母资产；分镜、视频、参考视频的批量与 Agent 自动生成默认走快速版。"
                "合并成片只使用已生成视频片段，缺视频时应提示缺失并停止，不得自动补生成或自动精修。"
            )
            payload["quality_recommendations"] = await _build_video_quality_recommendations(
                project_name=ctx.project_name,
                project=project,
            )
            return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}]}
        except FileNotFoundError as exc:
            return {
                "content": [{"type": "text", "text": f"项目未找到或缺 project.json: {exc}"}],
                "is_error": True,
            }
        except ValueError as exc:
            return {
                "content": [{"type": "text", "text": f"无法解析视频模型能力: {exc}"}],
                "is_error": True,
            }
        except Exception as exc:  # noqa: BLE001
            return tool_error("get_video_capabilities", exc)

    return _handler


# ---------------------------------------------------------------------------
# generate_episode_script
# ---------------------------------------------------------------------------


def _resolve_step1_path(project_path: Path, episode: int, project_data: dict[str, Any]) -> tuple[Path, str]:
    """Return (step1_md path, hint text for missing-file error)."""
    content_mode = project_data.get("content_mode", "narration")
    generation_mode = effective_mode(project=project_data, episode={})
    drafts_path = project_path / "drafts" / f"episode_{episode}"
    if generation_mode == "reference_video":
        return drafts_path / "step1_reference_units.md", "split-reference-video-units subagent (Step 1)"
    if content_mode == "drama":
        return drafts_path / "step1_normalized_script.md", "normalize_drama_script tool"
    return drafts_path / "step1_segments.md", "片段拆分 (Step 1)"


def _ensure_step1_script_splitting_comments(step1_path: Path, project_data: dict[str, Any]) -> None:
    try:
        profile = current_profile(project_data)
        template_id = profile.get("id")
        script_hash = profile.get("hash")
    except Exception:
        return
    if not template_id or not script_hash:
        return
    content = step1_path.read_text(encoding="utf-8")
    head = "\n".join(content.splitlines()[:8])
    if "script_splitting_hash:" in head and "script_splitting_template_id:" in head:
        return
    comments = (
        f"<!-- script_splitting_template_id: {template_id} -->\n"
        f"<!-- script_splitting_hash: {script_hash} -->\n\n"
    )
    step1_path.write_text(comments + content.lstrip(), encoding="utf-8")


def generate_episode_script_tool(ctx: ToolContext):
    @tool(
        "generate_episode_script",
        "调用项目配置的文本模型生成 JSON 剧本（agent 内置 in-process MCP tool，"
        "无 sandbox provider 域名约束）。输出固定写入 {project}/scripts/episode_N.json，"
        "dry_run=true 时仅返回 prompt 不调用 API。",
        {
            "type": "object",
            "properties": {
                "episode": {"type": "integer", "description": "剧集编号"},
                "dry_run": {"type": "boolean", "description": "仅显示 prompt，不调用模型"},
            },
            "required": ["episode"],
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        episode: int | None = None
        step1_path: Path | None = None
        try:
            episode = int(args["episode"])
            dry_run = bool(args.get("dry_run"))

            project_path = ctx.project_path
            try:
                project_data = json.loads((project_path / "project.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                project_data = {}

            step1_path, hint = _resolve_step1_path(project_path, episode, project_data)
            if not step1_path.exists():
                return {
                    "content": [{"type": "text", "text": f"❌ 未找到 Step 1 文件: {step1_path}\n   请先完成 {hint}"}],
                    "is_error": True,
                }
            _ensure_step1_script_splitting_comments(step1_path, project_data)

            if dry_run:
                generator = ScriptGenerator(project_path)
                prompt = await generator.build_prompt(episode)
                prompt_path = _write_dry_run_prompt(project_path, episode, "generate_episode_script", prompt)
                return _dry_run_tool_result("DRY RUN — 以下是将发送给文本模型的 Prompt", prompt, prompt_path)

            generator = await ScriptGenerator.create(project_path)
            result_path = await generator.generate(episode=episode)
            return {"content": [{"type": "text", "text": _episode_script_summary_text(result_path)}]}
        except FileNotFoundError as exc:
            return {"content": [{"type": "text", "text": f"❌ 文件错误: {exc}"}], "is_error": True}
        except Exception as exc:  # noqa: BLE001
            repair_result = await auto_repair_runtime_failure(
                script_id="text_structured_output_probe",
                tool_name="generate_episode_script",
                failure_stage="episode_script_json_generation",
                exc=exc,
                context={
                    "project_name": ctx.project_name,
                    "project_path": str(ctx.project_path),
                    "episode": episode,
                    "step1_path": str(step1_path) if step1_path is not None else None,
                    "dry_run": bool(args.get("dry_run")),
                },
            )
            repair_note = format_auto_repair_note(repair_result)
            if repair_result and repair_result.get("repaired") and episode is not None and not bool(args.get("dry_run")):
                try:
                    generator = await ScriptGenerator.create(ctx.project_path)
                    result_path = await generator.generate(episode=episode)
                    text = _episode_script_summary_text(result_path)
                    notes = [repair_note, "agent_ops 修复成功，已自动重试 generate_episode_script 并恢复主流程。"]
                    text = "\n\n".join(note for note in [text, *notes] if note)
                    return {"content": [{"type": "text", "text": text}]}
                except Exception as retry_exc:  # noqa: BLE001
                    notes = [
                        repair_note,
                        f"agent_ops 修复后自动重试仍失败: {retry_exc}",
                        f"原始错误: {exc}",
                    ]
                    return tool_error("generate_episode_script", retry_exc, [note for note in notes if note])
            return tool_error("generate_episode_script", exc, [repair_note] if repair_note else None)

    return _handler


# ---------------------------------------------------------------------------
# normalize_drama_script
# ---------------------------------------------------------------------------


async def _fetch_caps_with_fallback(project: dict[str, Any]) -> tuple[int | None, list[int]]:
    """Script normalization is best-effort: prompt生成 不该被能力查询失败堵住。

    Soft-fallbacks to ``_FALLBACK_SUPPORTED_DURATIONS`` so the LLM still
    receives a usable duration constraint set if the resolver hiccups.
    """
    try:
        default_int, durations = await fetch_video_caps(project)
    except (FileNotFoundError, ValueError) as exc:
        logger.info("video_capabilities 不可解析，使用 fallback [4,6,8]：%s", exc)
        return None, list(_FALLBACK_SUPPORTED_DURATIONS)
    except Exception as exc:  # noqa: BLE001
        logger.warning("video_capabilities 查询异常，使用 fallback [4,6,8]：%s", exc)
        return None, list(_FALLBACK_SUPPORTED_DURATIONS)
    if not durations:
        return default_int, list(_FALLBACK_SUPPORTED_DURATIONS)
    return default_int, durations


def normalize_drama_script_tool(ctx: ToolContext):
    @tool(
        "normalize_drama_script",
        "把 source/ 小说原文（或指定 source 文件）转化为 Markdown 规范化剧本，保存到 "
        "drafts/episode_N/step1_normalized_script.md，供 generate_episode_script 消费。"
        "dry_run=true 时仅返回 prompt。",
        {
            "type": "object",
            "properties": {
                "episode": {"type": "integer", "description": "剧集编号"},
                "source": {
                    "type": "string",
                    "description": "指定小说源文件路径（相对项目目录）；默认读取 source/ 下所有文本",
                },
                "dry_run": {"type": "boolean", "description": "仅显示 prompt，不调用模型"},
            },
            "required": ["episode"],
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        episode: int | None = None

        async def _run() -> dict[str, Any]:
            nonlocal episode
            episode = int(args["episode"])
            source = args.get("source")
            dry_run = bool(args.get("dry_run"))

            project_path = ctx.project_path
            project = ctx.pm.load_project(ctx.project_name)

            try:
                novel_text, source_files = _read_episode_source_text(project_path, episode, source)
            except FileNotFoundError as exc:
                return {"content": [{"type": "text", "text": f"❌ {exc}"}], "is_error": True}
            except ValueError as exc:
                return {"content": [{"type": "text", "text": f"❌ {exc}"}], "is_error": True}

            if not novel_text.strip():
                return {"content": [{"type": "text", "text": "❌ 小说原文为空"}], "is_error": True}

            project_for_prompt = _project_for_drama_normalization(project)
            default_duration, supported_durations = await _fetch_caps_with_fallback(project_for_prompt)
            script_profile = _resolve_drama_script_profile(project_for_prompt)
            prompt = build_normalize_prompt(
                novel_text=novel_text,
                project_overview=project_for_prompt.get("overview", {}),
                style=project_for_prompt.get("style", ""),
                characters=project_for_prompt.get("characters", {}),
                scenes=project_for_prompt.get("scenes", {}),
                props=project_for_prompt.get("props", {}),
                default_duration=default_duration,
                supported_durations=supported_durations,
                episode=episode,
                script_splitting_profile=script_profile,
            )

            if dry_run:
                prompt_path = _write_dry_run_prompt(project_path, episode, "normalize_drama_script", prompt)
                return _dry_run_tool_result("DRY RUN — 以下是将发送给文本模型的 Prompt", prompt, prompt_path)

            generator = await TextGenerator.create(TextTaskType.SCRIPT, project_name=ctx.project_name)
            result = await generator.generate(
                TextGenerationRequest(prompt=prompt, max_output_tokens=16000),
                project_name=ctx.project_name,
            )
            response = _strip_markdown_fence(result.text)
            scene_count = _validate_normalized_drama_step1(
                response,
                episode=episode,
                script_profile=script_profile,
                supported_durations=supported_durations,
            )

            drafts_dir = project_path / "drafts" / f"episode_{episode}"
            drafts_dir.mkdir(parents=True, exist_ok=True)
            step1_path = drafts_dir / "step1_normalized_script.md"
            step1_content = (
                f"<!-- script_splitting_template_id: {script_profile.get('id')} -->\n"
                f"<!-- script_splitting_hash: {script_profile.get('hash')} -->\n\n"
                f"{response.strip()}"
            )
            step1_path.write_text(step1_content, encoding="utf-8")

            source_summary = ", ".join(path.relative_to(project_path).as_posix() for path in source_files)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"✅ 规范化剧本已保存: {step1_path}\n"
                            f"📄 源文件: {source_summary}\n"
                            f"📊 生成统计: {scene_count} 个场景"
                        ),
                    }
                ]
            }

        try:
            return await _run()
        except Exception as exc:  # noqa: BLE001
            return await auto_repair_tool_error(
                "normalize_drama_script",
                exc,
                ctx=ctx,
                args=args,
                failure_stage="drama_step1_normalization",
                retry=_run,
                skip_expected_errors=True,
            )

    return _handler


__all__ = [
    "get_video_capabilities_tool",
    "generate_episode_script_tool",
    "normalize_drama_script_tool",
]
