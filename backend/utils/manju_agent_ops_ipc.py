#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Direct IPC endpoint for safe Manju agent_ops validation previews."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_SCRIPT = BACKEND_ROOT / "agent_ops" / "scripts" / "agent_script_registry.py"
REGISTRY_SCRIPT_ARG = str(Path("agent_ops") / "scripts" / "agent_script_registry.py")
_OUTPUT_TAIL_LIMIT = 20000
_ALLOWED_ACTIONS = {"validate", "list", "failure-examples", "run"}
_ALLOWED_FIELDS = {"action", "script_id", "all_defaults", "dry_run", "timeout_seconds"}


@dataclass(frozen=True)
class AgentOpsRunRequest:
    action: Literal["validate", "list", "failure-examples", "run"] = "validate"
    script_id: str | None = None
    all_defaults: bool = False
    dry_run: bool = False
    timeout_seconds: int = 600


def _tail(value: str | bytes | None, limit: int = _OUTPUT_TAIL_LIMIT) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = value
    if len(text) <= limit:
        return text
    return text[-limit:]


def _require_bool(data: dict[str, Any], field: str, default: bool = False) -> bool:
    value = data.get(field, default)
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _require_timeout_seconds(data: dict[str, Any]) -> int:
    value = data.get("timeout_seconds", 600)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("timeout_seconds must be an integer")
    if value < 1 or value > 1800:
        raise ValueError("timeout_seconds must be between 1 and 1800")
    return value


def _request_from_mapping(data: dict[str, Any]) -> AgentOpsRunRequest:
    extra = sorted(set(data) - _ALLOWED_FIELDS)
    if extra:
        raise ValueError(f"Unsupported IPC field(s): {', '.join(extra)}")

    action = data.get("action", "validate")
    if not isinstance(action, str) or action not in _ALLOWED_ACTIONS:
        raise ValueError(f"Unsupported IPC action: {action}")

    script_id = data.get("script_id")
    if script_id is not None and not isinstance(script_id, str):
        raise ValueError("script_id must be a string")

    return AgentOpsRunRequest(
        action=action,  # type: ignore[arg-type]
        script_id=script_id,
        all_defaults=_require_bool(data, "all_defaults"),
        dry_run=_require_bool(data, "dry_run"),
        timeout_seconds=_require_timeout_seconds(data),
    )


def _normalize_body(body: AgentOpsRunRequest | dict[str, Any] | None) -> AgentOpsRunRequest:
    if body is None:
        return AgentOpsRunRequest()
    if isinstance(body, AgentOpsRunRequest):
        return _request_from_mapping(
            {
                "action": body.action,
                "script_id": body.script_id,
                "all_defaults": body.all_defaults,
                "dry_run": body.dry_run,
                "timeout_seconds": body.timeout_seconds,
            }
        )
    if isinstance(body, dict):
        return _request_from_mapping(body)
    raise ValueError("agent_ops IPC body must be an object")


def _build_registry_args(body: AgentOpsRunRequest) -> list[str]:
    if not REGISTRY_SCRIPT.is_file():
        raise ValueError("agent_ops registry script not found")

    args = [body.action]
    if body.action == "run":
        if not body.dry_run:
            raise ValueError("run through IPC requires dry_run=true")
        if body.all_defaults:
            args.append("--all-defaults")
        elif body.script_id:
            args.append(body.script_id)
        else:
            raise ValueError("script_id or all_defaults is required for run")
        args.append("--dry-run")
        return args

    if body.all_defaults or body.script_id:
        raise ValueError(f"{body.action} does not accept script selection")
    return args


async def run_agent_ops(body: AgentOpsRunRequest | dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        request = _normalize_body(body)
        registry_args = _build_registry_args(request)
    except Exception as exc:  # noqa: BLE001 - IPC callers need a short structured error.
        return {
            "success": False,
            "returncode": None,
            "timed_out": False,
            "action": None,
            "script_id": None,
            "stdout": "",
            "stderr": "",
            "error": str(exc),
            "runtime": {
                "cwd": ".",
                "registry_script": "agent_ops/scripts/agent_script_registry.py",
            },
        }

    argv = [sys.executable, REGISTRY_SCRIPT_ARG, *registry_args]
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")

    try:
        completed = await asyncio.to_thread(
            subprocess.run,
            argv,
            cwd=BACKEND_ROOT,
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=request.timeout_seconds,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "success": False,
            "returncode": None,
            "timed_out": True,
            "action": request.action,
            "script_id": request.script_id,
            "stdout": _tail(exc.stdout),
            "stderr": _tail(exc.stderr),
            "runtime": {
                "cwd": ".",
                "registry_script": "agent_ops/scripts/agent_script_registry.py",
            },
        }

    return {
        "success": completed.returncode == 0,
        "returncode": completed.returncode,
        "timed_out": False,
        "action": request.action,
        "script_id": request.script_id,
        "stdout": _tail(completed.stdout),
        "stderr": _tail(completed.stderr),
        "runtime": {
            "cwd": ".",
            "registry_script": "agent_ops/scripts/agent_script_registry.py",
        },
    }
