"""Per-session context shared by Manju MCP tool handlers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Awaitable, Callable

from lib.config.resolver import ConfigResolver
from lib.db import async_session_factory
from lib.project_manager import ProjectManager


class ToolContext:
    """Bind a tool handler to one agent session's project + projects_root.

    The agent never names the project explicitly — every tool is closure-bound
    to ``project_name`` via ``build_arcreel_mcp_server(project_name=...)``.
    """

    def __init__(self, project_name: str, projects_root: Path, pm: ProjectManager | None = None):
        self.project_name = project_name
        self.projects_root = projects_root
        # Avoid ``ProjectManager.from_cwd()`` — the server main process cwd is
        # the repo root, not ``projects/<name>/``. Tests may inject a fake pm.
        self.pm: ProjectManager = pm if pm is not None else ProjectManager(str(projects_root))

    @property
    def project_path(self) -> Path:
        return self.pm.get_project_path(self.project_name)


_TOOL_TEXT_MAX_BYTES_DEFAULT = 256 * 1024
_TOOL_TEXT_MAX_BYTES_MIN = 32 * 1024
_TOOL_TEXT_MAX_BYTES_MAX = 1024 * 1024


def _bounded_int_env(name: str, default: int, min_value: int, max_value: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return min(max(value, min_value), max_value)


def _format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def tool_text_max_bytes() -> int:
    """Return the MCP text payload budget for a single tool response."""
    return _bounded_int_env(
        "ASSISTANT_MCP_TOOL_TEXT_MAX_BYTES",
        _TOOL_TEXT_MAX_BYTES_DEFAULT,
        _TOOL_TEXT_MAX_BYTES_MIN,
        _TOOL_TEXT_MAX_BYTES_MAX,
    )


def compact_tool_text(
    text: str,
    *,
    label: str = "工具输出",
    source_path: Path | str | None = None,
    max_bytes: int | None = None,
) -> str:
    """Keep tool text results below the SDK JSON transport danger zone."""
    budget = max_bytes if max_bytes is not None else tool_text_max_bytes()
    encoded = text.encode("utf-8")
    if len(encoded) <= budget:
        return text

    preview = encoded[:budget].decode("utf-8", errors="ignore").rstrip()
    source_note = (
        f"完整内容已保存: {source_path}"
        if source_path is not None
        else "完整内容未随工具结果返回；请查看后端日志或对应项目文件。"
    )
    return (
        f"{label}过大，已截断显示，避免 agent JSON 传输超限。\n"
        f"原始大小: {_format_bytes(len(encoded))}; 预览上限: {_format_bytes(budget)}。\n"
        f"{source_note}\n\n"
        f"--- 预览开始 ---\n{preview}\n--- 预览结束 ---"
    )


def tool_result_text(
    text: str,
    *,
    label: str = "工具输出",
    source_path: Path | str | None = None,
) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": compact_tool_text(text, label=label, source_path=source_path)}]}


def tool_error(name: str, exc: BaseException, log: list[str] | None = None) -> dict[str, Any]:
    """Build the ``{"is_error": True}`` response every SDK tool handler emits on failure."""
    msg = f"{name} 失败: {exc}"
    text = "\n".join([msg, *log]) if log else msg
    result = tool_result_text(text, label=f"{name} 错误输出")
    result["is_error"] = True
    return result


EXPECTED_TOOL_ERRORS = (FileNotFoundError, ValueError, PermissionError)
DEFAULT_AGENT_OPS_SCRIPT_ID = "manga_workflow_tool_recovery"


async def auto_repair_tool_error(
    name: str,
    exc: BaseException,
    *,
    ctx: ToolContext,
    args: dict[str, Any] | None = None,
    failure_stage: str | None = None,
    script_id: str = DEFAULT_AGENT_OPS_SCRIPT_ID,
    retry: Callable[[], Awaitable[dict[str, Any]]] | None = None,
    skip_expected_errors: bool = True,
) -> dict[str, Any]:
    """Route unexpected MCP tool failures through agent_ops and retry after repair.

    User/data errors such as missing files and invalid arguments should remain
    normal tool errors. They are not code repair opportunities.
    """
    if skip_expected_errors and isinstance(exc, EXPECTED_TOOL_ERRORS):
        return tool_error(name, exc)

    from utils.agent_ops_autofix import auto_repair_runtime_failure, format_auto_repair_note

    repair_result = await auto_repair_runtime_failure(
        script_id=script_id,
        tool_name=name,
        failure_stage=failure_stage or name,
        exc=exc,
        context={
            "project_name": ctx.project_name,
            "project_path": str(ctx.project_path),
            "args": args or {},
        },
    )
    repair_note = format_auto_repair_note(repair_result)
    if repair_result and repair_result.get("repaired") and retry is not None:
        try:
            result = await retry()
            if result.get("is_error") is True:
                retry_text = result.get("content", [{}])[0].get("text", "重试仍返回错误")
                return tool_error(name, RuntimeError(str(retry_text)), [repair_note] if repair_note else None)
            text = result.get("content", [{}])[0].get("text")
            if isinstance(text, str):
                notes = [text, repair_note, f"agent_ops 修复成功，已自动重试 {name} 并恢复主流程。"]
                result["content"][0]["text"] = "\n\n".join(note for note in notes if note)
            return result
        except Exception as retry_exc:  # noqa: BLE001
            notes = [
                repair_note,
                f"agent_ops 修复后自动重试仍失败: {retry_exc}",
                f"原始错误: {exc}",
            ]
            return tool_error(name, retry_exc, [note for note in notes if note])
    return tool_error(name, exc, [repair_note] if repair_note else None)


async def fetch_video_caps(project: dict[str, Any]) -> tuple[int | None, list[int]]:
    """Resolve ``(default_duration, supported_durations)`` for an MCP tool call.

    Single source of truth for video model capability lookup across SDK MCP
    tools (``enqueue_videos`` and ``text_generation`` both depend on this).
    Returns the raw resolved durations; callers decide whether an empty result
    is a hard error (video generation) or a soft fallback (script normalization).
    """
    resolver = ConfigResolver(async_session_factory)
    caps = await resolver.video_capabilities_for_project(project)
    durations = [int(d) for d in caps.get("supported_durations") or []]
    default = caps.get("default_duration")
    default_int = int(default) if isinstance(default, int | float) else None
    return default_int, durations


def validate_script_filename(value: str) -> str:
    """Reject any agent-provided ``script`` arg that is not a bare basename.

    Agents must reference scripts by filename only (e.g. ``episode_1.json``);
    the project root is bound by ``ToolContext`` and the ``scripts/`` subdir
    is fixed inside ``ProjectManager.load_script``. Any path separator —
    including a ``scripts/`` prefix or ``..`` segments — is rejected.
    """
    if not isinstance(value, str) or not value:
        raise ValueError("script 文件名不能为空")
    if "/" in value or "\\" in value or value in (".", ".."):
        raise ValueError(f"script 必须是纯文件名，禁止路径分隔符: {value!r}")
    return value
