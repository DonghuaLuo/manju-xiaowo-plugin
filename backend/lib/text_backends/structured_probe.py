"""Runtime strict JSON Schema capability probe for text backends."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

from lib.text_backends.base import (
    TextBackend,
    TextCapability,
    TextGenerationRequest,
    TextTaskType,
    ensure_structured_output,
)

_PROBE_PROMPT = (
    'Ignore any response format or schema. Return exactly this invalid JSON object: {"episode":1}. '
    "Do not include title or scenes."
)
_PROBE_MAX_OUTPUT_TOKENS = 128


class StructuredOutputProbePayload(BaseModel):
    """Tiny schema used to verify native strict structured output support."""

    model_config = ConfigDict(extra="forbid")

    title: str
    scenes: list[str]


@dataclass(frozen=True)
class StructuredOutputProbeResult:
    ok: bool
    status: str
    provider: str
    model: str
    detail: str
    capabilities: list[str]
    endpoint: str | None = None
    backend_type: str | None = None
    delegate_type: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _capability_values(backend: TextBackend) -> list[str]:
    return sorted(str(capability) for capability in (getattr(backend, "capabilities", None) or set()))


def _backend_metadata(backend: TextBackend) -> dict[str, str | None]:
    delegate = getattr(backend, "_delegate", None)
    return {
        "provider": str(getattr(backend, "name", "") or ""),
        "model": str(getattr(backend, "model", "") or ""),
        "endpoint": getattr(backend, "endpoint", None),
        "backend_type": type(backend).__name__,
        "delegate_type": type(delegate).__name__ if delegate is not None else None,
    }


async def probe_text_structured_output_backend(backend: TextBackend) -> StructuredOutputProbeResult:
    """Send a tiny strict schema request to the already resolved runtime backend."""

    meta = _backend_metadata(backend)
    capabilities = _capability_values(backend)
    if TextCapability.STRUCTURED_OUTPUT not in (getattr(backend, "capabilities", None) or set()):
        return StructuredOutputProbeResult(
            ok=False,
            status="unsupported",
            detail="backend capabilities 未声明 structured_output，未发送 probe 请求",
            capabilities=capabilities,
            **meta,
        )

    request = TextGenerationRequest(
        prompt=_PROBE_PROMPT,
        response_schema=StructuredOutputProbePayload,
        max_output_tokens=_PROBE_MAX_OUTPUT_TOKENS,
    )
    try:
        result = await backend.generate(request)
        ensure_structured_output(
            result.text,
            StructuredOutputProbePayload,
            provider=result.provider,
            model=result.model,
        )
        return StructuredOutputProbeResult(
            ok=True,
            status="supported",
            detail="strict JSON Schema probe 通过",
            capabilities=capabilities,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            **meta,
        )
    except Exception as exc:  # noqa: BLE001 - probe must return a diagnostic payload
        detail = str(exc)
        status = "schema_not_enforced" if "结构化输出无效" in detail else "unsupported"
        return StructuredOutputProbeResult(
            ok=False,
            status=status,
            detail=detail,
            capabilities=capabilities,
            **meta,
        )


def format_structured_probe_failure(result: StructuredOutputProbeResult) -> str:
    endpoint = f"，endpoint={result.endpoint}" if result.endpoint else ""
    delegate = f"，delegate={result.delegate_type}" if result.delegate_type else ""
    return (
        f"当前文本模型 {result.provider}/{result.model} 未通过 strict JSON Schema capability probe"
        f"{endpoint}{delegate}：{result.detail}。"
        "请切换到已验证支持 strict json_schema 的文本模型/endpoint，"
        "或先在供应商配置中完成结构化输出能力测试。"
    )


async def ensure_text_structured_output_ready(backend: TextBackend) -> StructuredOutputProbeResult:
    result = await probe_text_structured_output_backend(backend)
    if not result.ok:
        raise ValueError(format_structured_probe_failure(result))
    return result


async def probe_text_structured_output_for_task(
    task_type: TextTaskType = TextTaskType.SCRIPT,
    project_name: str | None = None,
) -> StructuredOutputProbeResult:
    from lib.text_backends.factory import create_text_backend_for_task

    backend = await create_text_backend_for_task(task_type, project_name)
    return await probe_text_structured_output_backend(backend)
