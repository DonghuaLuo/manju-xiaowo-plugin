"""User-facing summaries for provider quota and rate-limit errors."""

from __future__ import annotations

import re
from typing import Any


_REQUEST_ID_PATTERNS = (
    re.compile(r"\brequest\s*id[:：]?\s*([a-zA-Z0-9-]+)", re.I),
    re.compile(r"\brequest[_-]id['\"]?\s*[:=]\s*['\"]?([a-zA-Z0-9-]+)", re.I),
)

_MODEL_PATTERNS = (
    re.compile(r"\bfor\s+the\s+\[([^\]]+)\]\s+model\b", re.I),
    re.compile(r"\bmodel['\"]?\s*[:=]\s*['\"]([a-zA-Z0-9_.:-]+)['\"]", re.I),
)

_ERROR_CODE_PATTERNS = (
    re.compile(r"\bcode=['\"]([a-zA-Z0-9_.:-]+)['\"]", re.I),
    re.compile(r"['\"]code['\"]\s*:\s*['\"]([a-zA-Z0-9_.:-]+)['\"]", re.I),
    re.compile(r"\berror[_-]?code['\"]?\s*[:=]\s*['\"]?([a-zA-Z0-9_.:-]+)", re.I),
)

_QUOTA_PATTERNS = (
    re.compile(r"\bsetlimitexceeded\b", re.I),
    re.compile(r"\binference\s+limit\b", re.I),
    re.compile(r"\bquota\b", re.I),
    re.compile(r"\binsufficient[_ -]?quota\b", re.I),
    re.compile(r"\bresource[_ -]?exhausted\b", re.I),
    re.compile(r"\bcredit[s]?\b.*\b(exhausted|limit|insufficient)\b", re.I),
    re.compile(r"\b(exhausted|insufficient)\b.*\bcredit[s]?\b", re.I),
    re.compile(r"\bbilling\b.*\b(limit|quota|disabled|required)\b", re.I),
    re.compile(r"\b(spend|spending)\b.*\blimit\b", re.I),
    re.compile(r"余额不足|额度不足|用量.*(超|满|耗尽)|配额.*(超|满|耗尽)", re.I),
)

_RATE_LIMIT_PATTERNS = (
    re.compile(r"\brate[_ -]?limit", re.I),
    re.compile(r"\btoo\s+many\s+requests\b", re.I),
    re.compile(r"\b429\b", re.I),
    re.compile(r"\b(qps|rpm|tpm)\b.*\blimit\b", re.I),
    re.compile(r"频率.*(超|高)|并发.*(超|满)|请求过于频繁", re.I),
)


def _first_match(patterns: tuple[re.Pattern[str], ...], message: str) -> str | None:
    for pattern in patterns:
        match = pattern.search(message)
        if match:
            return match.group(1)
    return None


def _extract_task_model(task: dict[str, Any] | None) -> str | None:
    payload = task.get("payload") if task else None
    if not isinstance(payload, dict):
        return None
    for key in ("model", "model_id", "video_model", "image_model", "text_model"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _append_details(
    parts: list[str],
    *,
    provider_id: str | None,
    model: str | None,
    code: str | None,
    request_id: str | None,
) -> None:
    details = []
    if provider_id:
        details.append(f"供应商：{provider_id}")
    if model:
        details.append(f"模型：{model}")
    if code:
        details.append(f"错误码：{code}")
    if request_id:
        details.append(f"请求 ID：{request_id}")
    if details:
        parts.append("；".join(details) + "。")


def summarize_generation_error(
    error: BaseException | str,
    *,
    provider_id: str | None = None,
    task: dict[str, Any] | None = None,
) -> str:
    """Return a friendly message for quota/rate-limit errors; otherwise raw text."""

    message = str(error)
    if not message:
        return message

    request_id = _first_match(_REQUEST_ID_PATTERNS, message)
    model = _first_match(_MODEL_PATTERNS, message) or _extract_task_model(task)
    code = _first_match(_ERROR_CODE_PATTERNS, message)
    lowered = message.lower()
    is_safe_experience_limit = "safe experience mode" in lowered or (code or "").lower() == "setlimitexceeded"

    if is_safe_experience_limit:
        parts = [
            "火山方舟提示该模型已达到后台设置的推理上限，模型服务已暂停。",
            "请到火山方舟模型开通/激活页面调整或关闭 Safe Experience Mode（安全体验模式），或提高该模型额度后重试。",
        ]
        _append_details(parts, provider_id=provider_id, model=model, code=code, request_id=request_id)
        return "".join(parts)

    if any(pattern.search(message) for pattern in _QUOTA_PATTERNS):
        parts = [
            "供应商模型用量、余额或配额已达上限，当前生成任务已停止。",
            "请到对应供应商控制台检查余额、账单、模型配额或体验模式限制，调整后再重试。",
        ]
        _append_details(parts, provider_id=provider_id, model=model, code=code, request_id=request_id)
        return "".join(parts)

    if any(pattern.search(message) for pattern in _RATE_LIMIT_PATTERNS):
        parts = [
            "供应商请求频率或并发已超限，当前生成任务已失败。",
            "请稍后重试，或降低并发数量、提高供应商限流额度后再生成。",
        ]
        _append_details(parts, provider_id=provider_id, model=model, code=code, request_id=request_id)
        return "".join(parts)

    return message
