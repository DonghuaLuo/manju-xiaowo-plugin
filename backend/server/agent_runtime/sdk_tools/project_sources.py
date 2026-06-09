"""SDK MCP tools for source-file inspection, episode splitting, and reset.

The operations run in-process against the bound project so source handling,
episode splitting, and fixed-artifact cleanup share one cross-platform path.
"""

from __future__ import annotations

import json
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool

from lib.text_metrics import count_reading_units, find_reading_unit_offset
from server.agent_runtime.sdk_tools._context import ToolContext, tool_error, tool_result_text

_SUPPORTED_LANGUAGES = ("zh", "en", "vi")
_SOURCE_EXTENSIONS = {".txt", ".text", ".md"}
_EPISODE_SOURCE_RE = re.compile(r"^episode_\d+\.(?:txt|text|md)$", re.IGNORECASE)
_ZH_SENTENCE_ENDINGS = frozenset({"。", "！", "？", "…"})
_LATIN_SENTENCE_ENDINGS = frozenset({".", "!", "?", "…"})


def _json_result(payload: dict[str, Any]) -> dict[str, Any]:
    return tool_result_text(json.dumps(payload, ensure_ascii=False, indent=2), label="项目源文件工具输出")


def _positive_episode(value: Any) -> int:
    episode = int(value)
    if episode < 1:
        raise ValueError(f"episode 必须 >= 1，收到: {value!r}")
    return episode


def _source_dir(project_path: Path) -> Path:
    source_dir_unresolved = project_path / "source"
    if source_dir_unresolved.is_symlink():
        raise ValueError(f"source/ 不能是符号链接: {source_dir_unresolved}")
    source_dir = source_dir_unresolved.resolve()
    if not source_dir.is_dir():
        raise FileNotFoundError(f"项目缺 source/ 目录: {source_dir}")
    return source_dir


def _source_files(project_path: Path) -> list[Path]:
    source_dir = _source_dir(project_path)
    return sorted(
        (
            path
            for path in source_dir.iterdir()
            if path.is_file() and path.suffix.lower() in _SOURCE_EXTENSIONS
        ),
        key=lambda path: path.name.lower(),
    )


def _preferred_source(files: list[Path]) -> Path | None:
    remaining = next((path for path in files if path.name == "_remaining.txt"), None)
    if remaining is not None:
        return remaining
    originals = [path for path in files if not _EPISODE_SOURCE_RE.match(path.name) and not path.name.startswith("_")]
    if len(originals) == 1:
        return originals[0]
    if originals:
        return originals[0]
    return files[0] if files else None


def _resolve_source(project_path: Path, source: Any | None) -> Path:
    files = _source_files(project_path)
    if source is None or str(source).strip() == "":
        selected = _preferred_source(files)
        if selected is None:
            raise FileNotFoundError(f"source/ 下未找到文本文件（支持: {sorted(_SOURCE_EXTENSIONS)}）")
        return selected

    source_dir = _source_dir(project_path)
    raw_source = Path(str(source))
    source_path = raw_source.resolve() if raw_source.is_absolute() else (project_path / raw_source).resolve()
    if not source_path.is_relative_to(source_dir):
        raise ValueError(f"源文件必须位于 {source_dir} 内，收到: {source_path}")
    if not source_path.is_file():
        raise FileNotFoundError(f"源文件不存在或不是普通文件: {source_path}")
    if source_path.suffix.lower() not in _SOURCE_EXTENSIONS:
        raise ValueError(f"源文件扩展名不支持: {source_path.name}")
    return source_path


def _resolve_language(project: dict[str, Any], language: Any | None) -> str:
    raw = language if language is not None and str(language).strip() else project.get("source_language")
    code = str(raw or "zh").strip().lower()
    if code not in _SUPPORTED_LANGUAGES:
        raise ValueError(f"不支持的 language={raw!r}（可选: {list(_SUPPORTED_LANGUAGES)}）")
    return code


def _count_chars(text: str) -> int:
    return sum(1 for char in text if not char.isspace())


def _line_count(text: str) -> int:
    if text == "":
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _find_char_offset(text: str, target_count: int) -> int:
    counted = 0
    lines = text.split("\n")
    pos = 0

    for line_idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            pos += len(line)
            if line_idx < len(lines) - 1:
                pos += 1
            continue

        for char in line:
            if not char.strip():
                pos += 1
                continue
            counted += 1
            if counted >= target_count:
                return pos
            pos += 1

        if line_idx < len(lines) - 1:
            pos += 1

    return pos


def _find_natural_breakpoints(
    text: str,
    center_offset: int,
    *,
    window: int = 200,
    language: str | None = None,
) -> list[dict[str, Any]]:
    start = max(0, center_offset - window)
    end = min(len(text), center_offset + window)
    sentence_endings = _LATIN_SENTENCE_ENDINGS if language in ("en", "vi") else _ZH_SENTENCE_ENDINGS
    breakpoints: list[dict[str, Any]] = []

    for index in range(start, end):
        char = text[index]
        if char == "\n" and index + 1 < len(text) and text[index + 1] == "\n":
            breakpoints.append(
                {
                    "offset": index + 1,
                    "char": "\\n\\n",
                    "type": "paragraph",
                    "distance": abs(index + 1 - center_offset),
                }
            )
        elif char in sentence_endings:
            breakpoints.append(
                {
                    "offset": index + 1,
                    "char": char,
                    "type": "sentence",
                    "distance": abs(index + 1 - center_offset),
                }
            )

    breakpoints.sort(key=lambda bp: int(bp["distance"]))
    return breakpoints


def _find_anchor_near_target(text: str, anchor: str, target_offset: int, *, window: int = 500) -> list[int]:
    search_start = max(0, target_offset - window)
    search_end = min(len(text), target_offset + window)
    search_region = text[search_start:search_end]
    positions: list[int] = []
    start = 0
    while True:
        index = search_region.find(anchor, start)
        if index == -1:
            break
        positions.append(search_start + index + len(anchor))
        start = index + 1
    positions.sort(key=lambda pos: abs(pos - target_offset))
    return positions


def _source_info_payload(source_path: Path, *, language: str) -> dict[str, Any]:
    text = unicodedata.normalize("NFC", source_path.read_text(encoding="utf-8"))
    return {
        "source": f"source/{source_path.name}",
        "language": language,
        "file_size_bytes": source_path.stat().st_size,
        "line_count": _line_count(text),
        "nonempty_line_count": sum(1 for line in text.splitlines() if line.strip()),
        "char_count": len(text),
        "non_whitespace_char_count": _count_chars(text),
        "reading_units": count_reading_units(text, language),
        "has_trailing_newline": text.endswith("\n"),
    }


def list_source_files_tool(ctx: ToolContext):
    @tool(
        "list_source_files",
        "列出当前项目 source/ 下可用于分集的文本文件，并给出推荐源文件。"
        "用于阶段 2 开始时选择分集输入。",
        {"type": "object", "properties": {}},
    )
    async def _handler(_args: dict[str, Any]) -> dict[str, Any]:
        try:
            project_path = ctx.project_path
            files = _source_files(project_path)
            preferred = _preferred_source(files)
            payload = {
                "preferred_source": f"source/{preferred.name}" if preferred else None,
                "files": [
                    {
                        "source": f"source/{path.name}",
                        "size_bytes": path.stat().st_size,
                        "is_remaining": path.name == "_remaining.txt",
                        "is_episode": bool(_EPISODE_SOURCE_RE.match(path.name)),
                    }
                    for path in files
                ],
            }
            return _json_result(payload)
        except Exception as exc:  # noqa: BLE001
            return tool_error("list_source_files", exc)

    return _handler


def source_info_tool(ctx: ToolContext):
    @tool(
        "source_info",
        "输出 source 文本文件的安全统计信息，不返回正文。",
        {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "源文件路径，如 source/novel.txt；省略时使用推荐源文件"},
                "language": {"type": "string", "description": "阅读单位语言 zh/en/vi；省略时使用 project.json"},
            },
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            project = ctx.pm.load_project(ctx.project_name)
            language = _resolve_language(project, args.get("language"))
            source_path = _resolve_source(ctx.project_path, args.get("source"))
            return _json_result(_source_info_payload(source_path, language=language))
        except Exception as exc:  # noqa: BLE001
            return tool_error("source_info", exc)

    return _handler


def peek_split_point_tool(ctx: ToolContext):
    @tool(
        "peek_split_point",
        "按目标阅读单位探测 source 文件附近自然断点，返回上下文与 split_target_chars。"
        "用于分集前预览切分位置。",
        {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "源文件路径；省略时使用推荐源文件"},
                "target": {"type": "integer", "description": "目标阅读单位数"},
                "context": {"type": "integer", "description": "上下文窗口字符数，默认 200"},
                "language": {"type": "string", "description": "阅读单位语言 zh/en/vi；省略时使用 project.json"},
            },
            "required": ["target"],
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            target = int(args["target"])
            if target < 1:
                raise ValueError(f"target 必须 >= 1，收到: {target}")
            context = max(1, int(args.get("context") or 200))
            project = ctx.pm.load_project(ctx.project_name)
            language = _resolve_language(project, args.get("language"))
            source_path = _resolve_source(ctx.project_path, args.get("source"))
            text = unicodedata.normalize("NFC", source_path.read_text(encoding="utf-8"))
            total_units = count_reading_units(text, language)
            if total_units == 0:
                raise ValueError(f"源文件无可计阅读单位(language={language}): {source_path}")
            if target >= total_units:
                raise ValueError(f"目标阅读单位 ({target}) 超过或等于总阅读单位 ({total_units})")

            target_offset = find_reading_unit_offset(text, target, language)
            split_target_chars = _count_chars(text[:target_offset])
            ctx_start = max(0, target_offset - context)
            ctx_end = min(len(text), target_offset + context)
            payload = {
                "source": f"source/{source_path.name}",
                "language": language,
                "total_units": total_units,
                "target_units": target,
                "split_target_chars": split_target_chars,
                "target_offset": target_offset,
                "context_before": text[ctx_start:target_offset],
                "context_after": text[target_offset:ctx_end],
                "nearby_breakpoints": _find_natural_breakpoints(
                    text,
                    target_offset,
                    window=context,
                    language=language,
                )[:10],
            }
            return _json_result(payload)
        except Exception as exc:  # noqa: BLE001
            return tool_error("peek_split_point", exc)

    return _handler


def split_episode_tool(ctx: ToolContext):
    @tool(
        "split_episode",
        "按 peek_split_point 返回的 split_target_chars 和锚点文本生成 source/episode_N.txt"
        "与 source/_remaining.txt。dry_run=true 时只返回预览不写文件。",
        {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "源文件路径；省略时使用推荐源文件"},
                "episode": {"type": "integer", "description": "集数编号"},
                "target": {"type": "integer", "description": "peek_split_point 返回的 split_target_chars"},
                "anchor": {"type": "string", "description": "切分点前的锚点文本"},
                "context": {"type": "integer", "description": "锚点搜索窗口，默认 500"},
                "dry_run": {"type": "boolean", "description": "仅预览，不写文件"},
            },
            "required": ["episode", "target", "anchor"],
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            episode = _positive_episode(args["episode"])
            target = int(args["target"])
            if target < 1:
                raise ValueError(f"target 必须 >= 1，收到: {target}")
            anchor = str(args["anchor"])
            if not anchor:
                raise ValueError("anchor 不能为空")
            context = max(1, int(args.get("context") or 500))
            dry_run = bool(args.get("dry_run"))

            project_path = ctx.project_path
            source_path = _resolve_source(project_path, args.get("source"))
            text = unicodedata.normalize("NFC", source_path.read_text(encoding="utf-8"))
            target_offset = _find_char_offset(text, target)
            positions = _find_anchor_near_target(text, anchor, target_offset, window=context)
            if not positions:
                raise ValueError(f'在目标字数 {target} 附近未找到锚点文本: "{anchor}"')

            split_pos = positions[0]
            part_before = text[:split_pos]
            part_after = text[split_pos:]
            source_dir = _source_dir(project_path)
            episode_file = source_dir / f"episode_{episode}.txt"
            remaining_file = source_dir / "_remaining.txt"

            payload = {
                "source": f"source/{source_path.name}",
                "episode": episode,
                "dry_run": dry_run,
                "target_chars": target,
                "target_offset": target_offset,
                "split_offset": split_pos,
                "anchor_matches": len(positions),
                "episode_source": f"source/{episode_file.name}",
                "remaining_source": "source/_remaining.txt",
                "episode_char_count": len(part_before),
                "remaining_char_count": len(part_after),
                "episode_tail_preview": part_before[-50:],
                "remaining_head_preview": part_after[:50],
            }
            if not dry_run:
                episode_file.write_text(part_before, encoding="utf-8")
                remaining_file.write_text(part_after, encoding="utf-8")
                payload["written"] = [f"source/{episode_file.name}", "source/_remaining.txt"]
            return _json_result(payload)
        except Exception as exc:  # noqa: BLE001
            return tool_error("split_episode", exc)

    return _handler


def _remove_path(path: Path, *, project_path: Path) -> dict[str, Any]:
    rel = path.relative_to(project_path)
    if not path.exists() and not path.is_symlink():
        return {"path": str(rel).replace("\\", "/"), "status": "missing"}

    if path.is_symlink():
        path.unlink()
        return {"path": str(rel).replace("\\", "/"), "status": "removed_symlink"}

    resolved_project = project_path.resolve()
    resolved_path = path.resolve()
    if not resolved_path.is_relative_to(resolved_project):
        raise ValueError(f"拒绝删除项目目录外路径: {resolved_path}")

    if path.is_dir():
        shutil.rmtree(path)
        return {"path": str(rel).replace("\\", "/"), "status": "removed_dir"}
    path.unlink()
    return {"path": str(rel).replace("\\", "/"), "status": "removed_file"}


def reset_episode_artifacts_tool(ctx: ToolContext):
    @tool(
        "reset_episode_artifacts",
        "清理单集重跑所需的固定中间产物：scripts/episode_N.json、drafts/episode_N。"
        "默认保留 source/episode_N.txt，避免误从 _remaining.txt 重新切错集；"
        "确需重新切分原文时可显式 include_source=true。只接受集数，不能删除任意路径。",
        {
            "type": "object",
            "properties": {
                "episode": {"type": "integer", "description": "集数编号"},
                "include_source": {"type": "boolean", "description": "是否删除 source/episode_N.txt，默认 false；仅重新切分原文时启用"},
                "include_script": {"type": "boolean", "description": "是否删除 scripts/episode_N.json，默认 true"},
                "include_drafts": {"type": "boolean", "description": "是否删除 drafts/episode_N，默认 true"},
            },
            "required": ["episode"],
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            episode = _positive_episode(args["episode"])
            include_source = bool(args.get("include_source", False))
            include_script = bool(args.get("include_script", True))
            include_drafts = bool(args.get("include_drafts", True))
            if not any((include_source, include_script, include_drafts)):
                raise ValueError("至少选择一个 include_* 清理目标")

            project_path = ctx.project_path
            targets: list[Path] = []
            if include_source:
                targets.append(project_path / "source" / f"episode_{episode}.txt")
            if include_script:
                targets.append(project_path / "scripts" / f"episode_{episode}.json")
            if include_drafts:
                targets.append(project_path / "drafts" / f"episode_{episode}")

            payload = {"episode": episode, "removed": [_remove_path(path, project_path=project_path) for path in targets]}
            return _json_result(payload)
        except Exception as exc:  # noqa: BLE001
            return tool_error("reset_episode_artifacts", exc)

    return _handler


__all__ = [
    "list_source_files_tool",
    "source_info_tool",
    "peek_split_point_tool",
    "split_episode_tool",
    "reset_episode_artifacts_tool",
]
