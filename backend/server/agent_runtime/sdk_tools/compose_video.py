"""MCP wrapper for composing existing video clips."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import threading
from pathlib import Path
from types import ModuleType
from typing import Any

from claude_agent_sdk import tool

from server.agent_runtime.sdk_tools._context import (
    ToolContext,
    tool_error,
    tool_result_text,
    validate_script_filename,
)

_COMPOSE_MODULE: ModuleType | None = None
_CWD_LOCK = threading.Lock()


def _compose_script_path() -> Path:
    backend_root = Path(__file__).resolve().parents[3]
    return backend_root / "agent_runtime_profile" / ".claude" / "skills" / "compose-video" / "scripts" / "compose_video.py"


def _load_compose_module() -> ModuleType:
    global _COMPOSE_MODULE
    if _COMPOSE_MODULE is not None:
        return _COMPOSE_MODULE

    script_path = _compose_script_path()
    spec = importlib.util.spec_from_file_location("_manju_compose_video_mcp", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载视频合成模块: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _COMPOSE_MODULE = module
    return module


@contextlib.contextmanager
def _push_cwd(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def compose_video_tool(ctx: ToolContext):
    @tool(
        "compose_video",
        "把已生成的视频片段按剧本顺序合成为单集成片，可选 BGM 与转场。只合并现有片段，不触发视频生成。",
        {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "剧本文件名（如 episode_1.json），必须是纯文件名",
                },
                "output": {
                    "type": "string",
                    "description": "可选输出文件名；省略时按剧本章节名生成，产物固定写入 output/",
                },
                "music": {
                    "type": "string",
                    "description": "可选 BGM 文件路径；相对项目根解析，绝对路径也必须位于项目目录内",
                },
                "no_transitions": {
                    "type": "boolean",
                    "description": "true 时忽略剧本转场字段，全部使用 cut 直接拼接",
                },
            },
            "required": ["script"],
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        log = io.StringIO()
        try:
            script = validate_script_filename(args.get("script"))
            output = args.get("output") or None
            music = args.get("music") or None
            use_transitions = not bool(args.get("no_transitions"))

            module = _load_compose_module()
            if not module.check_ffmpeg():
                return {
                    "content": [{"type": "text", "text": module.FFMPEG_TOOLS_HINT}],
                    "is_error": True,
                }

            with _CWD_LOCK, _push_cwd(ctx.project_path), contextlib.redirect_stdout(log):
                output_path = module.compose_video(script, output, music, use_transitions=use_transitions)

            project_path = ctx.project_path.resolve()
            output_rel = output_path.resolve().relative_to(project_path).as_posix()
            text = "\n".join(
                part
                for part in (
                    f"compose_video 完成: {output_rel}",
                    log.getvalue().strip(),
                )
                if part
            )
            return tool_result_text(text, label="视频合成输出")
        except Exception as exc:  # noqa: BLE001
            captured = log.getvalue().strip()
            return tool_error("compose_video", exc, [captured] if captured else None)

    return _handler


__all__ = ["compose_video_tool"]
