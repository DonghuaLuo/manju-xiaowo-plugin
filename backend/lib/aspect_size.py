"""统一「比例优先、清晰度其次」的尺寸计算。

媒体生成的输出比例只有一个来源：项目的 ``aspect_ratio``。分辨率（预设档位或自定义值）
只决定清晰度规模，不决定比例。本模块把这条原则收口成纯函数，供使用像素尺寸的后端复用。
"""

from __future__ import annotations

import logging
import math
import re

logger = logging.getLogger(__name__)

DEFAULT_SHORT_EDGE = 720

IMAGE_TIER_SHORT_EDGE: dict[str, int] = {"512px": 512, "1K": 1024, "2K": 1440, "3K": 1728, "4K": 2160}
VIDEO_TIER_SHORT_EDGE: dict[str, int] = {"480p": 480, "720p": 720, "1024p": 1024, "1080p": 1080, "4K": 2160}

_DEFAULT_ASPECT: tuple[int, int] = (9, 16)
_WH_RE = re.compile(r"^\s*(\d+)\s*[xX×*]\s*(\d+)\s*$")
_RATIO_SEP_RE = re.compile(r"[:：]")


def parse_aspect_ratio(aspect_ratio: str) -> tuple[int, int]:
    """把 ``"9:16"`` 解析成约简互质的 ``(9, 16)``；非法值回退默认竖屏比例。"""
    try:
        parts = _RATIO_SEP_RE.split(aspect_ratio.strip())
        if len(parts) != 2:
            raise ValueError(aspect_ratio)
        aw, ah = int(parts[0]), int(parts[1])
        if aw <= 0 or ah <= 0:
            raise ValueError(aspect_ratio)
    except (AttributeError, ValueError, IndexError):
        logger.warning("无法解析 aspect_ratio=%r，回退默认 %d:%d", aspect_ratio, *_DEFAULT_ASPECT)
        return _DEFAULT_ASPECT
    g = math.gcd(aw, ah)
    return aw // g, ah // g


def aspect_size(
    aspect_ratio: str,
    short_edge: int,
    *,
    round_to: int = 16,
    max_long_edge: int | None = None,
    max_total_pixels: int | None = None,
    max_ratio: float | None = None,
) -> tuple[int, int]:
    """按比例 + 短边目标算出精确遵循比例、且被 ``round_to`` 整除的 ``(宽, 高)``。"""
    aw, ah = parse_aspect_ratio(aspect_ratio)

    if max_ratio is not None:
        ratio = max(aw / ah, ah / aw)
        if ratio > max_ratio + 1e-9:
            logger.warning(
                "aspect_ratio=%s 比例 %.2f 超出后端支持上限 %.2f，可能被 API 拒绝或裁剪",
                aspect_ratio,
                ratio,
                max_ratio,
            )

    short_comp = min(aw, ah)
    long_comp = max(aw, ah)
    short_unit = round_to * short_comp
    t = max(1, round(short_edge / short_unit))

    if max_long_edge is not None:
        max_t_long = max_long_edge // (round_to * long_comp)
        t = min(t, max(1, max_t_long))

    if max_total_pixels is not None:
        denom = aw * ah * round_to * round_to
        max_t_pixels = math.isqrt(max_total_pixels // denom) if denom > 0 else 0
        t = min(t, max(1, max_t_pixels))

    t = max(1, t)
    return aw * round_to * t, ah * round_to * t


def resolution_to_short_edge(
    resolution: str | None,
    *,
    tier_map: dict[str, int],
    default_short: int = DEFAULT_SHORT_EDGE,
) -> int:
    """把分辨率规范化成短边像素；自定义 ``宽*高`` 只取短边，比例仍由项目决定。"""
    if resolution is None:
        return default_short
    s = resolution.strip()
    if not s:
        return default_short

    norm = {k.lower(): v for k, v in tier_map.items()}
    if s.lower() in norm:
        return norm[s.lower()]

    m = _WH_RE.match(s)
    if m:
        return min(int(m.group(1)), int(m.group(2)))

    if s.isdigit():
        return int(s)

    logger.warning("无法解析 resolution=%r，回退默认短边 %d", resolution, default_short)
    return default_short
