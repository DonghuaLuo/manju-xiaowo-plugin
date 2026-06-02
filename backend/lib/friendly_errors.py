"""User-facing summaries and classifications for generation provider errors."""

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

_REQUEST_TOO_LARGE_PATTERNS = (
    re.compile(r"\b413\b", re.I),
    re.compile(r"\b(payload|request|body)\b.*\btoo\s+large\b", re.I),
    re.compile(r"\brequest\s+entity\s+too\s+large\b", re.I),
    re.compile(r"请求体.*(过大|超限)|输入图.*(过大|超限)|base64.*(超过|超限)", re.I),
)

_MODERATION_PATTERNS = (
    re.compile(r"\b(content[_ -]?policy|moderation|safety|unsafe|blocked)\b", re.I),
    re.compile(r"内容.*(安全|违规|审核|拦截)|安全.*(拦截|拒绝|违规)", re.I),
)

_TIMEOUT_PATTERNS = (
    re.compile(r"\b(timeout|timed\s+out|deadline)\b", re.I),
    re.compile(r"超时|等待.*过长", re.I),
)

_PROVIDER_UNAVAILABLE_PATTERNS = (
    re.compile(r"\b(502|503|504)\b", re.I),
    re.compile(r"\b(service\s+unavailable|temporarily\s+unavailable|try\s+again\s+later)\b", re.I),
    re.compile(r"服务.*(不可用|繁忙|暂时)|稍后.*重试", re.I),
)

_DOWNLOAD_PATTERNS = (
    re.compile(r"\b(download|connection\s+reset|connection\s+aborted|network)\b", re.I),
    re.compile(r"下载.*(失败|中断)|网络.*(失败|中断|异常)", re.I),
)

_CAPABILITY_PATTERNS = (
    re.compile(r"\b(unsupported|not\s+support|capability|invalidendpointormodel\.notfound)\b", re.I),
    re.compile(r"不支持|能力.*不匹配|模型不存在|没有访问权限", re.I),
)

_VALIDATION_PATTERNS = (
    re.compile(r"\b(400|bad\s+request|invalid\s+(argument|parameter|request|image))\b", re.I),
    re.compile(r"参数.*(错误|无效)|无效.*(图片|请求|参数)", re.I),
)

_FAILURE_SUGGESTIONS = {
    "moderation": "调整提示词、参考图或素材，避开供应商安全策略后重试。",
    "request_body_too_large": "减少参考图数量或降低输入图尺寸后重试。",
    "rate_limit": "稍后自动/手动重试，或降低并发、提高供应商限流额度。",
    "quota": "检查供应商余额、模型额度或体验模式限制后再重试。",
    "timeout": "稍后重试；若频繁出现，降低并发或改用历史成功率更高的供应商。",
    "provider_unavailable": "稍后重试，或临时切换到可用供应商。",
    "download_failed": "稍后重试；若 provider 任务已完成，可优先重试下载/接续。",
    "capability": "切换到支持当前分辨率、时长、参考图或音频能力的模型。",
    "validation": "检查提示词、文件、模型与参数是否符合供应商要求。",
    "unknown": "查看后端日志定位原始错误，再决定是否重试或换供应商。",
}


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


def classify_generation_failure(error: BaseException | str) -> dict[str, Any]:
    """Return a stable machine-readable failure category and retry hint."""

    message = str(error or "")
    lowered = message.lower()
    code = _first_match(_ERROR_CODE_PATTERNS, message)
    code_lowered = (code or "").lower()

    category = "unknown"
    retryable = False

    if any(pattern.search(message) for pattern in _MODERATION_PATTERNS):
        category = "moderation"
    elif any(pattern.search(message) for pattern in _REQUEST_TOO_LARGE_PATTERNS):
        category = "request_body_too_large"
    elif (
        "safe experience mode" in lowered
        or code_lowered == "setlimitexceeded"
        or any(pattern.search(message) for pattern in _QUOTA_PATTERNS)
    ):
        category = "quota"
    elif any(pattern.search(message) for pattern in _RATE_LIMIT_PATTERNS):
        category = "rate_limit"
        retryable = True
    elif any(pattern.search(message) for pattern in _TIMEOUT_PATTERNS):
        category = "timeout"
        retryable = True
    elif any(pattern.search(message) for pattern in _PROVIDER_UNAVAILABLE_PATTERNS):
        category = "provider_unavailable"
        retryable = True
    elif any(pattern.search(message) for pattern in _DOWNLOAD_PATTERNS):
        category = "download_failed"
        retryable = True
    elif any(pattern.search(message) for pattern in _CAPABILITY_PATTERNS):
        category = "capability"
    elif any(pattern.search(message) for pattern in _VALIDATION_PATTERNS):
        category = "validation"

    return {
        "failure_type": category,
        "retryable": retryable,
        "retry_suggestion": _FAILURE_SUGGESTIONS[category],
        "error_code": code,
    }


def append_failure_classification(
    message: str,
    classification: dict[str, Any],
    *,
    attempts: dict[str, Any] | None = None,
) -> str:
    """Append compact failure metadata to the user-facing task error."""

    failure_type = classification.get("failure_type") or "unknown"
    suggestion = classification.get("retry_suggestion") or _FAILURE_SUGGESTIONS["unknown"]
    parts = [f"失败类型：{failure_type}", f"建议：{suggestion}"]
    if attempts:
        current = attempts.get("attempt")
        max_attempts = attempts.get("max_attempts")
        if current is not None and max_attempts is not None:
            parts.insert(1, f"尝试次数：{current}/{max_attempts}")
    return f"{message}（{'；'.join(parts)}）"


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
