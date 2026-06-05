"""Rule-based preflight checks before video generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image


def _check(
    *,
    check_id: str,
    status: str,
    severity: str,
    message: str,
    autofix_available: bool = False,
    check_method: str = "rule",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": status,
        "severity": severity,
        "check_method": check_method,
        "message": message,
        "autofix_available": autofix_available,
        "details": details or {},
    }


def _aspect_ratio_from_image(path: str | Path) -> str | None:
    try:
        with Image.open(path) as img:
            width, height = img.size
    except (FileNotFoundError, OSError):
        return None
    if width <= 0 or height <= 0:
        return None
    ratio = width / height
    candidates = {
        "9:16": 9 / 16,
        "16:9": 16 / 9,
        "1:1": 1,
        "4:3": 4 / 3,
        "3:4": 3 / 4,
    }
    return min(candidates, key=lambda key: abs(candidates[key] - ratio))


def _image_info(path: str | Path) -> dict[str, Any] | None:
    try:
        with Image.open(path) as img:
            width, height = img.size
    except (FileNotFoundError, OSError):
        return None
    if width <= 0 or height <= 0:
        return None
    file_size = None
    try:
        file_size = Path(path).stat().st_size
    except OSError:
        pass
    return {"width": width, "height": height, "pixels": width * height, "file_size_bytes": file_size}


def _supported_aspect_ratios(capabilities: dict[str, Any] | None) -> list[str]:
    if not capabilities:
        return []
    constraints = capabilities.get("constraints")
    if isinstance(constraints, dict):
        raw = constraints.get("supported_aspect_ratios")
        if isinstance(raw, list):
            return [str(v) for v in raw]
    raw = capabilities.get("supported_aspect_ratios")
    if isinstance(raw, list):
        return [str(v) for v in raw]
    return []


def _capability_constraint(capabilities: dict[str, Any] | None, key: str) -> Any:
    if not capabilities:
        return None
    constraints = capabilities.get("constraints")
    if isinstance(constraints, dict) and constraints.get(key) is not None:
        return constraints.get(key)
    return capabilities.get(key)


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def run_video_input_preflight(
    *,
    project: dict[str, Any] | None,
    capabilities: dict[str, Any] | None,
    request: dict[str, Any],
) -> dict[str, Any]:
    """Return block/warn/autofix/manual checks for a prospective video request."""
    project = project or {}
    request = request or {}
    checks: list[dict[str, Any]] = []

    project_ratio = str(project.get("aspect_ratio") or "9:16")
    aspect_ratio = str(request.get("aspect_ratio") or project_ratio)
    supported_ratios = _supported_aspect_ratios(capabilities)
    if supported_ratios and aspect_ratio not in supported_ratios:
        checks.append(
            _check(
                check_id="aspect_ratio",
                status="block",
                severity="block",
                message=f"画面比例 {aspect_ratio} 不在当前 provider 支持范围内。",
                autofix_available=False,
                details={"aspect_ratio": aspect_ratio, "supported_aspect_ratios": supported_ratios},
            )
        )
    elif aspect_ratio != project_ratio:
        checks.append(
            _check(
                check_id="aspect_ratio",
                status="warn",
                severity="warn",
                message=f"请求比例 {aspect_ratio} 与项目比例 {project_ratio} 不一致，可能导致裁切或连续性下降。",
                autofix_available=True,
                details={"aspect_ratio": aspect_ratio, "project_aspect_ratio": project_ratio},
            )
        )
    else:
        checks.append(
            _check(
                check_id="aspect_ratio",
                status="ok",
                severity="ok",
                message="画面比例与项目设置一致。",
                details={"aspect_ratio": aspect_ratio},
            )
        )

    supported_durations = capabilities.get("supported_durations") if capabilities else None
    duration = request.get("duration_seconds")
    if duration is not None and isinstance(supported_durations, list) and supported_durations:
        try:
            duration_int = int(duration)
        except (TypeError, ValueError):
            checks.append(
                _check(
                    check_id="duration_supported",
                    status="block",
                    severity="block",
                    message="duration_seconds 必须是整数秒。",
                    details={"duration_seconds": duration},
                )
            )
        else:
            normalized = sorted({int(d) for d in supported_durations})
            if duration_int not in normalized:
                checks.append(
                    _check(
                        check_id="duration_supported",
                        status="block",
                        severity="block",
                        message=f"单任务时长 {duration_int}s 不在当前模型支持集合内。",
                        autofix_available=True,
                        details={"duration_seconds": duration_int, "supported_durations": normalized},
                    )
                )
            else:
                checks.append(
                    _check(
                        check_id="duration_supported",
                        status="ok",
                        severity="ok",
                        message="单任务时长符合当前模型能力。",
                        details={"duration_seconds": duration_int},
                    )
                )

    max_refs = capabilities.get("max_reference_images") if capabilities else None
    reference_count = request.get("reference_images_count")
    if reference_count is None:
        refs = request.get("reference_images")
        reference_count = len(refs) if isinstance(refs, list) else None
    if reference_count is not None and max_refs is not None:
        count = int(reference_count)
        max_count = int(max_refs)
        if count > max_count:
            checks.append(
                _check(
                    check_id="reference_count",
                    status="block",
                    severity="block",
                    message=f"参考图数量 {count} 超过当前模型上限 {max_count}。",
                    details={"reference_images_count": count, "max_reference_images": max_count},
                )
            )
        else:
            checks.append(
                _check(
                    check_id="reference_count",
                    status="ok",
                    severity="ok",
                    message="参考图数量符合当前模型上限。",
                    details={"reference_images_count": count, "max_reference_images": max_count},
                )
            )

    min_pixels = _positive_int(_capability_constraint(capabilities, "min_pixels"))
    max_file_size = _positive_int(_capability_constraint(capabilities, "max_file_size_bytes"))
    for field, check_id in (("first_frame_path", "first_frame_aspect_ratio"), ("last_frame_path", "last_frame_aspect_ratio")):
        frame_path = request.get(field)
        if not frame_path:
            continue
        frame_info = _image_info(str(frame_path))
        frame_ratio = _aspect_ratio_from_image(str(frame_path))
        if frame_ratio is None:
            checks.append(
                _check(
                    check_id=check_id,
                    status="warn",
                    severity="warn",
                    message=f"无法读取 {field} 的图片比例，请人工确认素材可用。",
                    check_method="manual",
                    details={field: frame_path},
                )
            )
        elif min_pixels is not None and frame_info and int(frame_info["pixels"]) < min_pixels:
            checks.append(
                _check(
                    check_id=f"{field}_min_pixels",
                    status="block",
                    severity="block",
                    message=f"{field} 图片尺寸低于当前模型最小像素要求。",
                    autofix_available=True,
                    details={field: frame_path, "pixels": frame_info["pixels"], "min_pixels": min_pixels},
                )
            )
        elif (
            max_file_size is not None
            and frame_info
            and frame_info.get("file_size_bytes") is not None
            and int(frame_info["file_size_bytes"]) > max_file_size
        ):
            checks.append(
                _check(
                    check_id=f"{field}_file_size",
                    status="block",
                    severity="block",
                    message=f"{field} 图片文件超过当前模型大小上限。",
                    autofix_available=True,
                    details={
                        field: frame_path,
                        "file_size_bytes": frame_info["file_size_bytes"],
                        "max_file_size_bytes": max_file_size,
                    },
                )
            )
        elif frame_ratio != aspect_ratio:
            checks.append(
                _check(
                    check_id=check_id,
                    status="block",
                    severity="block",
                    message=f"{field} 图片比例约为 {frame_ratio}，与请求比例 {aspect_ratio} 不一致。",
                    autofix_available=True,
                    details={field: frame_path, "image_aspect_ratio": frame_ratio, "aspect_ratio": aspect_ratio},
                )
            )
        else:
            checks.append(
                _check(
                    check_id=check_id,
                    status="ok",
                    severity="ok",
                    message=f"{field} 图片比例匹配请求比例。",
                    details={field: frame_path, "image_aspect_ratio": frame_ratio},
                )
            )

    generate_audio = request.get("generate_audio")
    supports_generate_audio = capabilities.get("supports_generate_audio") if capabilities else None
    if generate_audio is True and supports_generate_audio is False:
        checks.append(
            _check(
                check_id="generate_audio_supported",
                status="block",
                severity="block",
                message="当前模型不支持原生音频生成，请关闭音频或切换模型。",
                autofix_available=True,
                details={"generate_audio": True, "supports_generate_audio": False},
            )
        )
    elif generate_audio is not None and supports_generate_audio is not None:
        checks.append(
            _check(
                check_id="generate_audio_supported",
                status="ok",
                severity="ok",
                message="音频生成设置与当前模型能力兼容。",
                details={"generate_audio": bool(generate_audio), "supports_generate_audio": bool(supports_generate_audio)},
            )
        )

    checks.append(
        _check(
            check_id="subject_crop",
            status="manual",
            severity="warn",
            message="请人工确认角色脸部、身体和关键道具没有被裁出画面。",
            check_method="manual",
        )
    )
    checks.append(
        _check(
            check_id="first_last_consistency",
            status="manual",
            severity="warn",
            message="首版暂不做视觉 AI 判断；请人工确认首尾帧是同一角色、场景和连续时空。",
            check_method="vision_ai_pending",
        )
    )

    has_block = any(check["status"] == "block" for check in checks)
    has_warn = any(check["status"] in {"warn", "manual"} for check in checks)
    return {
        "status": "block" if has_block else ("warn" if has_warn else "ok"),
        "checks": checks,
        "autofix_available": any(bool(check.get("autofix_available")) for check in checks),
    }
