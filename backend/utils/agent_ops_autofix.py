#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Automatic agent_ops diagnostics/repair for runtime tool failures."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_SCRIPT = BACKEND_ROOT / "agent_ops" / "scripts" / "agent_script_registry.py"
REGISTRY_SCRIPT_ARG = str(Path("agent_ops") / "scripts" / "agent_script_registry.py")
REPAIR_RUNS_DIR = BACKEND_ROOT / "agent_ops" / "repair-runs"

_OUTPUT_TAIL_LIMIT = 20000
_TRACEBACK_TAIL_LIMIT = 8000
_DISABLED_VALUES = {"0", "false", "no", "off"}


def _tail(value: str | bytes | None, limit: int = _OUTPUT_TAIL_LIMIT) -> str:
    if value is None:
        return ""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    if len(text) <= limit:
        return text
    return text[-limit:]


def _is_enabled() -> bool:
    value = os.environ.get("MANJU_AGENT_OPS_AUTO_REPAIR", "1").strip().lower()
    return value not in _DISABLED_VALUES


def _timeout_seconds() -> int:
    raw = os.environ.get("MANJU_AGENT_OPS_AUTO_REPAIR_TIMEOUT_SECONDS", "600")
    try:
        value = int(raw)
    except ValueError:
        return 600
    return min(max(value, 1), 1800)


def _current_python_env(env: dict[str, str]) -> dict[str, str]:
    """Make SDK-launched helpers resolve Python to the current plugin runtime."""
    result = dict(env)
    python_dir = Path(sys.executable).parent
    if not python_dir.exists():
        return result
    path_key = next((key for key in os.environ if key.lower() == "path"), "PATH")
    current_path = result.get(path_key) or os.environ.get(path_key, "")
    prepend = [str(path) for path in (python_dir, python_dir / "Scripts") if path.exists()]
    if prepend:
        result[path_key] = os.pathsep.join([*prepend, current_path]) if current_path else os.pathsep.join(prepend)
    result.setdefault("PYTHONUTF8", "1")
    result.setdefault("PYTHONIOENCODING", "utf-8")
    return result


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {str(key): _json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [_json_safe(item) for item in value]
        return repr(value)


def _relative_to_backend(path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(BACKEND_ROOT).as_posix()
    except ValueError:
        return str(path)


def _repair_task_path(script_id: str) -> Path:
    safe_script_id = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in script_id)
    return REPAIR_RUNS_DIR / f"runtime_{safe_script_id}_{_utc_stamp()}.json"


def _exception_payload(exc: BaseException) -> dict[str, str]:
    formatted = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback_tail": _tail(formatted, _TRACEBACK_TAIL_LIMIT),
    }


def write_runtime_repair_task(
    *,
    script_id: str,
    tool_name: str,
    failure_stage: str,
    exc: BaseException,
    context: dict[str, Any] | None = None,
) -> Path:
    REPAIR_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = _repair_task_path(script_id)
    payload = {
        "schema_version": 1,
        "repair_agent_type": "ops_agent",
        "trigger": "runtime_failure",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "script_id": script_id,
        "tool_name": tool_name,
        "failure_stage": failure_stage,
        "backend_root": str(BACKEND_ROOT),
        "context": _json_safe(context or {}),
        "exception": _exception_payload(exc),
        "recommended_registry_check": (
            f"{subprocess.list2cmdline([sys.executable])} "
            f"{subprocess.list2cmdline([REGISTRY_SCRIPT_ARG])} run {script_id}"
        ),
        "agent_command_env": "MANJU_AGENT_OPS_AGENT_COMMAND",
        "required_agent_actions": [
            "复现或解释 runtime_failure 中的失败路径。",
            "读取 registry 记录的 entrypoints、source_files、evidence 和 failure_examples 定位原因。",
            "只修改 registry 记录 repair_write_allowlist 中声明的路径范围。",
            "修复后运行 recommended_registry_check 和相关回归测试。",
        ],
        "success_contract": [
            "原失败工具再次运行时不再被同类错误阻塞。",
            "若 strict JSON Schema 不可用，流程必须自动进入 non_strict_validated 兜底并通过本地校验后再写盘。",
            "修复不得绕过本地 Pydantic、Step 1 对齐或路径围栏校验。",
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _run_registry_check(script_id: str, timeout_seconds: int) -> dict[str, Any]:
    if not REGISTRY_SCRIPT.is_file():
        return {
            "success": False,
            "returncode": None,
            "timed_out": False,
            "stdout": "",
            "stderr": "",
            "error": "agent_ops registry script not found",
        }
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    argv = [sys.executable, REGISTRY_SCRIPT_ARG, "run", script_id]
    try:
        completed = subprocess.run(
            argv,
            cwd=BACKEND_ROOT,
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "success": False,
            "returncode": None,
            "timed_out": True,
            "stdout": _tail(exc.stdout),
            "stderr": _tail(exc.stderr),
            "error": f"registry check timed out after {timeout_seconds}s",
        }
    return {
        "success": completed.returncode == 0,
        "returncode": completed.returncode,
        "timed_out": False,
        "stdout": _tail(completed.stdout),
        "stderr": _tail(completed.stderr),
        "error": None,
    }


def _load_registry_module() -> ModuleType | None:
    if not REGISTRY_SCRIPT.is_file():
        return None
    spec = importlib.util.spec_from_file_location("manju_agent_script_registry_runtime", REGISTRY_SCRIPT)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _select_registry_record(registry: ModuleType, script_id: str) -> tuple[Any | None, str | None]:
    try:
        records, errors = registry._select_records(BACKEND_ROOT, script_id, all_defaults=False)
    except Exception as exc:  # noqa: BLE001 - auto repair must not mask original failure.
        return None, str(exc)
    if errors:
        return None, "; ".join(str(error) for error in errors)
    if not records:
        return None, f"registry record not found: {script_id}"
    return records[0], None


def _render_agent_command(
    registry: ModuleType,
    *,
    template: str,
    repair_task: Path,
    script_id: str,
    version: str,
    failed_command: str,
) -> str:
    shell_arg = getattr(registry, "_shell_arg", lambda value: subprocess.list2cmdline([str(value)]))
    current_python = getattr(registry, "_current_python_command", lambda: subprocess.list2cmdline([sys.executable]))
    expanded = template
    replacements = {
        "{repair_task}": shell_arg(repair_task),
        "{script_id}": script_id,
        "{version}": version,
        "{failed_command}": shell_arg(failed_command),
        "{python}": current_python(),
        "{python_executable}": current_python(),
    }
    for token, value in replacements.items():
        expanded = expanded.replace(token, str(value))
    return expanded


def _repair_agent_prompt(*, repair_task: Path, script_id: str, failed_command: str) -> str:
    return "\n".join(
        [
            "你是 Manju agent_ops 自动修复 agent。",
            "",
            "目标：根据运行时修复任务定位并修复 Manju 后端代码/agent_ops 记录问题。",
            "",
            f"- backend 根目录: {BACKEND_ROOT}",
            f"- repair_task: {repair_task}",
            f"- script_id: {script_id}",
            f"- failed_command: {failed_command}",
            "",
            "必须遵守：",
            "1. 先读取 repair_task JSON，再读取其中推荐的 registry 记录、source_files、evidence、failure_examples。",
            "2. 只修改 registry 记录 repair_write_allowlist 允许的路径范围。",
            "3. 优先做最小修复，不做无关重构。",
            "4. 不要要求用户手动执行脚本；修复完成后直接结束并说明修改点。",
            "5. registry 检查会由宿主进程在你结束后自动运行，你不需要启动额外长期进程。",
        ]
    )


async def _build_sdk_repair_env() -> dict[str, str]:
    from lib.config.env_keys import OTHER_PROVIDER_ENV_KEYS
    from lib.config.service import build_anthropic_env_dict
    from lib.db import async_session_factory

    async with async_session_factory() as session:
        env = await build_anthropic_env_dict(session)
    for key in OTHER_PROVIDER_ENV_KEYS:
        env[key] = ""
    return _current_python_env(env)


async def _run_sdk_agent_repair_async(
    *,
    repair_task: Path,
    script_id: str,
    failed_command: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    try:
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
        from claude_agent_sdk.types import SystemPromptPreset
    except Exception as exc:  # noqa: BLE001
        return {
            "success": False,
            "returncode": None,
            "timed_out": False,
            "command": "claude_agent_sdk.query",
            "stdout": "",
            "stderr": "",
            "error": f"claude_agent_sdk is not available: {exc}",
        }

    env = await _build_sdk_repair_env()
    prompt = _repair_agent_prompt(
        repair_task=repair_task,
        script_id=script_id,
        failed_command=failed_command,
    )
    options = ClaudeAgentOptions(
        cwd=str(BACKEND_ROOT),
        setting_sources=["project"],
        allowed_tools=["Read", "Write", "Edit", "Grep", "Glob"],
        max_turns=30,
        system_prompt=SystemPromptPreset(
            type="preset",
            preset="claude_code",
            append=(
                "你正在 Manju 插件后端的 agent_ops 自动修复通道中运行。"
                "只处理 repair_task 指定的问题，保持中文简洁回复。"
            ),
        ),
        env=env,
    )

    lines: list[str] = []
    result_subtype = ""

    async def _consume() -> None:
        nonlocal result_subtype
        async for message in query(prompt=prompt, options=options):
            name = type(message).__name__
            if name == "AssistantMessage":
                content = getattr(message, "content", None)
                lines.append(str(content))
            elif isinstance(message, ResultMessage):
                result_subtype = str(getattr(message, "subtype", "") or "")
                result = getattr(message, "result", None)
                if result:
                    lines.append(str(result))

    try:
        await asyncio.wait_for(_consume(), timeout=timeout_seconds)
    except TimeoutError:
        return {
            "success": False,
            "returncode": None,
            "timed_out": True,
            "command": "claude_agent_sdk.query",
            "stdout": _tail("\n".join(lines)),
            "stderr": "",
            "error": f"repair agent timed out after {timeout_seconds}s",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "success": False,
            "returncode": None,
            "timed_out": False,
            "command": "claude_agent_sdk.query",
            "stdout": _tail("\n".join(lines)),
            "stderr": "",
            "error": f"repair agent failed: {exc}",
        }

    success = not result_subtype or result_subtype == "success"
    return {
        "success": success,
        "returncode": 0 if success else 1,
        "timed_out": False,
        "command": "claude_agent_sdk.query",
        "stdout": _tail("\n".join(lines)),
        "stderr": "",
        "error": None if success else f"repair agent finished with subtype {result_subtype}",
    }


def _run_default_sdk_agent_repair(
    *,
    repair_task: Path,
    script_id: str,
    failed_command: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    return asyncio.run(
        _run_sdk_agent_repair_async(
            repair_task=repair_task,
            script_id=script_id,
            failed_command=failed_command,
            timeout_seconds=timeout_seconds,
        )
    )


def _run_agent_repair(
    *,
    script_id: str,
    repair_task: Path,
    failed_command: str,
    timeout_seconds: int,
) -> dict[str, Any] | None:
    command_template = os.environ.get("MANJU_AGENT_OPS_AGENT_COMMAND")
    command = "claude_agent_sdk.query"
    registry = _load_registry_module()
    if registry is None:
        return {
            "success": False,
            "returncode": None,
            "timed_out": False,
            "stdout": "",
            "stderr": "",
            "error": "agent_ops registry module could not be loaded",
        }
    record, record_error = _select_registry_record(registry, script_id)
    if record is None:
        return {
            "success": False,
            "returncode": None,
            "timed_out": False,
            "stdout": "",
            "stderr": "",
            "error": record_error or "registry record could not be selected",
        }

    before = registry._repair_file_snapshot(BACKEND_ROOT, keep_backups=True)
    try:
        try:
            if command_template:
                command = _render_agent_command(
                    registry,
                    template=command_template,
                    repair_task=repair_task,
                    script_id=script_id,
                    version=getattr(record, "version", ""),
                    failed_command=failed_command,
                )
                completed = subprocess.run(
                    command,
                    cwd=BACKEND_ROOT,
                    shell=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_seconds,
                    check=False,
                )
                repair_result = {
                    "success": completed.returncode == 0,
                    "returncode": completed.returncode,
                    "timed_out": False,
                    "mode": "external_command",
                    "command": command,
                    "stdout": _tail(completed.stdout),
                    "stderr": _tail(completed.stderr),
                    "error": None
                    if completed.returncode == 0
                    else f"repair agent failed with exit code {completed.returncode}",
                }
            else:
                repair_result = _run_default_sdk_agent_repair(
                    repair_task=repair_task,
                    script_id=script_id,
                    failed_command=failed_command,
                    timeout_seconds=timeout_seconds,
                )
                repair_result.setdefault("mode", "default_sdk")
            after = registry._repair_file_snapshot(BACKEND_ROOT)
        except subprocess.TimeoutExpired as exc:
            return {
                "success": False,
                "returncode": None,
                "timed_out": True,
                "mode": "external_command" if command_template else "default_sdk",
                "command": command,
                "stdout": _tail(exc.stdout),
                "stderr": _tail(exc.stderr),
                "error": f"repair agent timed out after {timeout_seconds}s",
            }

        scope_violation = registry._check_repair_scope(BACKEND_ROOT, record, before, after)
        if scope_violation is not None:
            registry._restore_repair_changes(BACKEND_ROOT, before, after)
            return {
                "success": False,
                "returncode": repair_result.get("returncode"),
                "timed_out": False,
                "mode": repair_result.get("mode"),
                "command": repair_result.get("command"),
                "stdout": repair_result.get("stdout", ""),
                "stderr": repair_result.get("stderr", ""),
                "error": "repair agent modified paths outside repair_write_allowlist; changes restored",
                "changed_paths": list(scope_violation.changed_paths),
                "allowed_paths": list(scope_violation.allowed_paths),
            }
        return repair_result
    finally:
        registry._cleanup_repair_snapshot(before)


def _auto_repair_runtime_failure_sync(
    *,
    script_id: str,
    tool_name: str,
    failure_stage: str,
    exc: BaseException,
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    if not _is_enabled():
        return {
            "enabled": False,
            "script_id": script_id,
            "tool_name": tool_name,
            "failure_stage": failure_stage,
        }

    timeout_seconds = _timeout_seconds()
    repair_task = write_runtime_repair_task(
        script_id=script_id,
        tool_name=tool_name,
        failure_stage=failure_stage,
        exc=exc,
        context=context,
    )
    agent_repair = _run_agent_repair(
        script_id=script_id,
        repair_task=repair_task,
        failed_command=f"{tool_name}:{failure_stage}",
        timeout_seconds=timeout_seconds,
    )
    registry_check = _run_registry_check(script_id, timeout_seconds)
    return {
        "enabled": True,
        "script_id": script_id,
        "tool_name": tool_name,
        "failure_stage": failure_stage,
        "repair_task": _relative_to_backend(repair_task),
        "agent_command_configured": bool(os.environ.get("MANJU_AGENT_OPS_AGENT_COMMAND")),
        "agent_repair_attempted": agent_repair is not None,
        "agent_repair_mode": (agent_repair or {}).get("mode"),
        "agent_repair": agent_repair,
        "registry_check": registry_check,
        "repaired": bool(agent_repair and agent_repair.get("success") and registry_check.get("success")),
    }


async def auto_repair_runtime_failure(
    *,
    script_id: str,
    tool_name: str,
    failure_stage: str,
    exc: BaseException,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Trigger agent_ops automatically without hiding the original tool error."""
    try:
        return await asyncio.to_thread(
            _auto_repair_runtime_failure_sync,
            script_id=script_id,
            tool_name=tool_name,
            failure_stage=failure_stage,
            exc=exc,
            context=context,
        )
    except Exception as repair_exc:  # noqa: BLE001 - original failure must remain visible.
        return {
            "enabled": True,
            "script_id": script_id,
            "tool_name": tool_name,
            "failure_stage": failure_stage,
            "error": f"agent_ops auto repair failed: {repair_exc}",
        }


def format_auto_repair_note(result: dict[str, Any] | None) -> str:
    if not result:
        return ""
    if result.get("enabled") is False:
        return "agent_ops 自动修复已关闭（MANJU_AGENT_OPS_AUTO_REPAIR=0）。"
    if result.get("error"):
        return f"agent_ops 自动修复触发失败: {result['error']}"

    lines = ["agent_ops 自动处理已触发。"]
    repair_task = result.get("repair_task")
    if repair_task:
        lines.append(f"- 已写入运行时修复任务: {repair_task}")

    agent_repair = result.get("agent_repair")
    if result.get("agent_repair_attempted"):
        mode = result.get("agent_repair_mode")
        if agent_repair and agent_repair.get("success"):
            if mode == "external_command":
                lines.append("- 已调用 MANJU_AGENT_OPS_AGENT_COMMAND 修复 agent，命令退出成功。")
            else:
                lines.append("- 已自动启动内置 Claude Agent SDK 修复 agent，执行成功。")
        else:
            error = (agent_repair or {}).get("error") or "修复 agent 未成功"
            lines.append(f"- 已调用修复 agent，但未完成修复: {error}")
    else:
        lines.append("- 修复 agent 未启动，本次只自动诊断并生成修复任务。")

    registry_check = result.get("registry_check") or {}
    if registry_check:
        status = "通过" if registry_check.get("success") else "未通过"
        returncode = registry_check.get("returncode")
        lines.append(f"- registry 回归检查: {status} (returncode={returncode})")
    if result.get("repaired"):
        lines.append("- 修复 agent 已执行且 registry 回归通过。")
    return "\n".join(lines)
