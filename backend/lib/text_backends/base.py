"""文本生成服务层核心接口定义。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

_logger = logging.getLogger(__name__)


def warn_if_truncated(
    finish_reason: str | None,
    *,
    provider: str,
    model: str,
    output_tokens: int | None = None,
    truncation_values: tuple[str, ...] = ("length", "MAX_TOKENS", "max_tokens"),
) -> bool:
    """检测模型响应是否因 token 上限被截断，若是则 logger.warning。

    返回 True 表示被截断（供调用方用于进一步处理）。
    """
    if finish_reason is None:
        return False
    if finish_reason in truncation_values:
        _logger.warning(
            "%s/%s 输出被截断（finish_reason=%s, output_tokens=%s）：已达模型输出上限。"
            "考虑切换到更大输出上限的模型，或减少请求规模。",
            provider,
            model,
            finish_reason,
            output_tokens,
        )
        return True
    return False


def _format_validation_error(exc: ValidationError, *, limit: int = 3) -> str:
    parts: list[str] = []
    for err in exc.errors()[:limit]:
        loc = ".".join(str(part) for part in err.get("loc", ()))
        msg = str(err.get("msg", ""))
        parts.append(f"{loc}: {msg}" if loc else msg)
    if len(exc.errors()) > limit:
        parts.append(f"... 另有 {len(exc.errors()) - limit} 个错误")
    return "; ".join(parts)


def structured_output_error(text: str, schema: dict | type | None) -> str | None:
    """Return an error string when a structured text result is empty, non-JSON or schema-invalid."""
    if schema is None:
        return None
    if not isinstance(text, str) or not text.strip():
        return "模型返回空内容，无法解析为结构化输出"
    try:
        data = json.loads(text)
    except (TypeError, ValueError) as exc:
        return f"模型返回非 JSON 内容: {exc}"
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        try:
            schema.model_validate(data)
        except ValidationError as exc:
            return f"模型返回 JSON 但不符合 schema: {_format_validation_error(exc)}"
    return None


def ensure_structured_output(
    text: str,
    schema: dict | type | None,
    *,
    provider: str,
    model: str,
) -> None:
    if schema is None:
        return
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"{provider}/{model} 结构化输出无效：模型返回空内容，无法解析为结构化输出")
    try:
        data = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{provider}/{model} 结构化输出无效：模型返回非 JSON 内容: {exc}") from exc
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        try:
            schema.model_validate(data)
        except ValidationError as exc:
            raise ValueError(
                f"{provider}/{model} 结构化输出无效：模型返回 JSON 但不符合 schema: "
                f"{_format_validation_error(exc)}"
            ) from exc


class TextCapability(StrEnum):
    """文本后端支持的能力枚举。"""

    TEXT_GENERATION = "text_generation"
    STRUCTURED_OUTPUT = "structured_output"
    VISION = "vision"


class TextTaskType(StrEnum):
    """文本生成任务类型。"""

    SCRIPT = "script"
    OVERVIEW = "overview"
    STYLE_ANALYSIS = "style"


@dataclass
class ImageInput:
    """图片输入（用于 vision）。"""

    path: Path | None = None
    url: str | None = None


@dataclass
class TextGenerationRequest:
    """通用文本生成请求。各 Backend 忽略不支持的字段。"""

    prompt: str
    response_schema: dict | type | None = None
    images: list[ImageInput] | None = None
    system_prompt: str | None = None
    max_output_tokens: int | None = None


@dataclass
class TextGenerationResult:
    """通用文本生成结果。"""

    text: str
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


def resolve_schema(schema: dict | type[BaseModel]) -> dict:
    """将 response_schema 转为无 $ref 的纯 JSON Schema dict。

    - BaseModel 子类: 调用 model_json_schema() 后内联 $ref
    - dict: 直接内联 $ref（如果有）
    """
    if isinstance(schema, type):
        if not issubclass(schema, BaseModel):
            raise TypeError(f"resolve_schema 仅接受 dict 或 Pydantic BaseModel 子类，得到 {schema!r}")
        schema_dict: dict = schema.model_json_schema()
    else:
        schema_dict = schema

    defs = schema_dict.get("$defs", {})
    if not defs:
        return schema_dict

    def _inline(obj: Any, visited_refs: frozenset[str] = frozenset()) -> Any:
        if isinstance(obj, dict):
            if "$ref" in obj:
                ref_name = obj["$ref"].split("/")[-1]
                if ref_name in visited_refs:
                    raise ValueError(f"检测到 schema 中的循环引用: {ref_name}")
                resolved = _inline(defs[ref_name], visited_refs | {ref_name})
                extra = {k: v for k, v in obj.items() if k != "$ref"}
                return {**resolved, **extra} if extra else resolved
            return {k: _inline(v, visited_refs) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_inline(item, visited_refs) for item in obj]
        return obj

    result: dict = _inline(schema_dict)
    result.pop("$defs", None)
    return result


class TextBackend(Protocol):
    """文本生成后端协议。"""

    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def capabilities(self) -> set[TextCapability]: ...

    async def generate(self, request: TextGenerationRequest) -> TextGenerationResult: ...
