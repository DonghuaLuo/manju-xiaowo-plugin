"""
Image utility helpers.

Used by WebUI upload endpoints to validate, compress, and normalize uploaded images.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import shutil

from PIL import Image, ImageOps


def convert_image_bytes_to_png(content: bytes) -> bytes:
    """
    Convert arbitrary image bytes (jpg/png/webp/...) into PNG bytes.

    Raises:
        ValueError: if the input bytes are not a valid image.
    """
    try:
        with Image.open(BytesIO(content)) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")
            out = BytesIO()
            img.save(out, format="PNG")
            return out.getvalue()
    except Exception as e:
        raise ValueError("Invalid image") from e


def save_image_file_as_png(source_path: Path, output_path: Path) -> None:
    """Convert an image file to PNG and write it to output_path."""
    try:
        with Image.open(source_path) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(output_path, format="PNG")
    except Exception as e:
        raise ValueError("Invalid image") from e


def validate_image_bytes(content: bytes) -> None:
    """Validate that *content* is a decodable image.

    Raises:
        ValueError: if the input bytes are not a valid image.
    """
    try:
        with Image.open(BytesIO(content)) as img:
            img.verify()
    except Exception as e:
        raise ValueError("Invalid image") from e


def validate_image_file(source_path: Path) -> None:
    """Validate that source_path is a decodable image without copying it through IPC."""
    try:
        with Image.open(source_path) as img:
            img.verify()
    except Exception as e:
        raise ValueError("Invalid image") from e


_COMPRESS_THRESHOLD = 2 * 1024 * 1024  # 2 MB
_MAX_LONG_EDGE = 2048
_JPEG_QUALITY = 85


def compress_image_bytes(
    content: bytes,
    *,
    max_long_edge: int = _MAX_LONG_EDGE,
    quality: int = _JPEG_QUALITY,
) -> bytes:
    """
    将任意图片字节压缩为 JPEG：等比缩放到长边不超过 max_long_edge，
    quality 控制 JPEG 压缩质量。

    Raises:
        ValueError: if the input bytes are not a valid image.
    """
    try:
        with Image.open(BytesIO(content)) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode != "RGB":
                img = img.convert("RGB")

            w, h = img.size
            long_edge = max(w, h)
            if long_edge > max_long_edge:
                scale = max_long_edge / long_edge
                new_w = int(w * scale)
                new_h = int(h * scale)
                img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            out = BytesIO()
            img.save(out, format="JPEG", quality=quality, optimize=True)
            return out.getvalue()
    except Exception as e:
        raise ValueError("Invalid image") from e


def compress_image_file_to_path(
    source_path: Path,
    output_path: Path,
    *,
    max_long_edge: int = _MAX_LONG_EDGE,
    quality: int = _JPEG_QUALITY,
) -> None:
    """Compress an image file directly to a JPEG output path."""
    try:
        with Image.open(source_path) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode != "RGB":
                img = img.convert("RGB")

            w, h = img.size
            long_edge = max(w, h)
            if long_edge > max_long_edge:
                scale = max_long_edge / long_edge
                new_w = int(w * scale)
                new_h = int(h * scale)
                img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(output_path, format="JPEG", quality=quality, optimize=True)
    except Exception as e:
        raise ValueError("Invalid image") from e


def normalize_uploaded_image(
    content: bytes,
    original_suffix: str,
    *,
    compress_threshold: int = _COMPRESS_THRESHOLD,
) -> tuple[bytes, str]:
    """Validate (and optionally compress) an uploaded image.

    If *content* exceeds *compress_threshold* bytes the image is compressed to
    JPEG and ``".jpg"`` is returned as the suffix.  Otherwise the original
    bytes are returned after validation, together with *original_suffix* (or
    ``".png"`` when empty).

    Returns:
        ``(processed_content, final_suffix)``

    Raises:
        ValueError: if the input bytes are not a valid image.
    """
    if len(content) > compress_threshold:
        return compress_image_bytes(content), ".jpg"
    validate_image_bytes(content)
    return content, original_suffix or ".png"


def save_normalized_uploaded_image_file(
    source_path: Path,
    target_path: Path,
    original_suffix: str,
    *,
    compress_threshold: int = _COMPRESS_THRESHOLD,
) -> tuple[Path, str]:
    """Validate/copy a local upload path, compressing only when required.

    Small images are copied directly to the project target after validation.
    Large images follow the existing WebUI behavior and are compressed to JPEG.
    """
    if source_path.stat().st_size > compress_threshold:
        final_suffix = ".jpg"
        final_path = target_path.with_suffix(final_suffix)
        compress_image_file_to_path(source_path, final_path)
        return final_path, final_suffix

    final_suffix = original_suffix or ".png"
    final_path = target_path.with_suffix(final_suffix)
    validate_image_file(source_path)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if source_path.resolve() != final_path.resolve():
            shutil.copyfile(source_path, final_path)
    except OSError:
        shutil.copyfile(source_path, final_path)
    return final_path, final_suffix
