"""
Image utility helpers.

Used by WebUI upload endpoints to validate, compress, and normalize uploaded images.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from hashlib import sha1
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

_FORMAT_TO_MIME: dict[str, str] = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "JPG": "image/jpeg",
    "WEBP": "image/webp",
    "GIF": "image/gif",
    "BMP": "image/bmp",
    "TIFF": "image/tiff",
}

_MIME_TO_SUFFIX: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

_COMPRESS_THRESHOLD = 2 * 1024 * 1024  # 2 MB
_MAX_LONG_EDGE = 2048
_JPEG_QUALITY = 85


@dataclass(frozen=True)
class PreparedProviderImage:
    """A provider-safe temporary image plus metadata for audit/debug logs."""

    original_path: Path
    path: Path
    original_mime: str
    prepared_mime: str
    original_bytes: int
    prepared_bytes: int
    original_width: int
    original_height: int
    prepared_width: int
    prepared_height: int
    resized: bool
    transcoded: bool
    copied: bool
    purpose: str
    max_long_edge: int
    jpeg_quality: int | None

    @property
    def estimated_base64_bytes(self) -> int:
        return estimate_base64_size(self.prepared_bytes)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "source_path": str(self.original_path),
            "input_path": str(self.path),
            "source_mime": self.original_mime,
            "input_mime": self.prepared_mime,
            "source_bytes": self.original_bytes,
            "input_bytes": self.prepared_bytes,
            "source_size": {"width": self.original_width, "height": self.original_height},
            "input_size": {"width": self.prepared_width, "height": self.prepared_height},
            "estimated_base64_bytes": self.estimated_base64_bytes,
            "resized": self.resized,
            "transcoded": self.transcoded,
            "copied": self.copied,
            "max_long_edge": self.max_long_edge,
            "jpeg_quality": self.jpeg_quality,
        }


def estimate_base64_size(byte_count: int) -> int:
    """Return the exact base64 character count for a byte payload size."""
    if byte_count <= 0:
        return 0
    return ((byte_count + 2) // 3) * 4


def detect_image_mime(source_path: Path) -> str:
    """Detect the real image MIME by decoding the file, not by trusting suffix."""
    try:
        with Image.open(source_path) as img:
            detected = _FORMAT_TO_MIME.get(str(img.format or "").upper())
            if detected:
                return detected
    except Exception as e:
        raise ValueError("Invalid image") from e
    return "application/octet-stream"


def _has_alpha(img: Image.Image) -> bool:
    if img.mode in ("RGBA", "LA"):
        return True
    if img.mode == "P" and "transparency" in img.info:
        return True
    return False


def _fit_long_edge(width: int, height: int, max_long_edge: int) -> tuple[int, int]:
    if max_long_edge <= 0:
        return width, height
    long_edge = max(width, height)
    if long_edge <= max_long_edge:
        return width, height
    scale = max_long_edge / long_edge
    return max(1, int(width * scale)), max(1, int(height * scale))


def _provider_cache_path(
    source_path: Path,
    *,
    temp_dir: Path,
    suffix: str,
    purpose: str,
    max_long_edge: int,
    quality: int,
) -> Path:
    stat = source_path.stat()
    digest = sha1(
        "|".join(
            [
                str(source_path.resolve()),
                str(stat.st_mtime_ns),
                str(stat.st_size),
                purpose,
                str(max_long_edge),
                str(quality),
                suffix,
            ]
        ).encode("utf-8")
    ).hexdigest()[:16]
    safe_purpose = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in purpose) or "provider"
    return temp_dir / safe_purpose / f"{source_path.stem}-{digest}{suffix}"


def prepare_provider_image_input(
    source_path: Path,
    *,
    purpose: str = "video",
    temp_dir: Path | None = None,
    max_long_edge: int = _MAX_LONG_EDGE,
    jpeg_quality: int = 90,
    preserve_alpha: bool = True,
) -> PreparedProviderImage:
    """Prepare a temporary image for provider upload without mutating the source.

    The original master file remains untouched. Non-alpha images are normalized
    to JPEG when needed so base64 request bodies stay smaller and suffix-based
    provider MIME helpers receive a truthful extension.
    """
    source_path = Path(source_path)
    if not source_path.exists():
        raise FileNotFoundError(source_path)

    original_bytes = source_path.stat().st_size
    try:
        with Image.open(source_path) as img:
            original_mime = _FORMAT_TO_MIME.get(str(img.format or "").upper(), "application/octet-stream")
            img = ImageOps.exif_transpose(img)
            original_width, original_height = img.size
            target_width, target_height = _fit_long_edge(original_width, original_height, max_long_edge)
            resized = (target_width, target_height) != (original_width, original_height)
            has_alpha = _has_alpha(img)

            if resized:
                img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)

            if preserve_alpha and has_alpha:
                prepared_mime = "image/png"
                suffix = ".png"
                output_format = "PNG"
                if img.mode not in ("RGBA", "LA"):
                    img = img.convert("RGBA")
            else:
                prepared_mime = "image/jpeg"
                suffix = ".jpg"
                output_format = "JPEG"
                if img.mode != "RGB":
                    img = img.convert("RGB")

            temp_root = temp_dir or Path(tempfile.gettempdir()) / "manju-provider-inputs"
            output_path = _provider_cache_path(
                source_path,
                temp_dir=temp_root,
                suffix=suffix,
                purpose=purpose,
                max_long_edge=max_long_edge,
                quality=jpeg_quality,
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)

            source_suffix_mime = _MIME_TO_SUFFIX.get(original_mime)
            can_copy = (
                not resized
                and source_suffix_mime == suffix
                and source_path.suffix.lower() == suffix
                and (prepared_mime != "image/jpeg" or original_bytes <= _COMPRESS_THRESHOLD)
            )

            if can_copy:
                if source_path.resolve() != output_path.resolve():
                    shutil.copyfile(source_path, output_path)
                copied = True
                prepared_width, prepared_height = original_width, original_height
            else:
                if output_format == "JPEG":
                    img.save(output_path, format=output_format, quality=jpeg_quality, optimize=True)
                else:
                    img.save(output_path, format=output_format, optimize=True)
                copied = False
                prepared_width, prepared_height = img.size

            prepared_bytes = output_path.stat().st_size
            transcoded = prepared_mime != original_mime or not copied
            return PreparedProviderImage(
                original_path=source_path,
                path=output_path,
                original_mime=original_mime,
                prepared_mime=prepared_mime,
                original_bytes=original_bytes,
                prepared_bytes=prepared_bytes,
                original_width=original_width,
                original_height=original_height,
                prepared_width=prepared_width,
                prepared_height=prepared_height,
                resized=resized,
                transcoded=transcoded,
                copied=copied,
                purpose=purpose,
                max_long_edge=max_long_edge,
                jpeg_quality=jpeg_quality if prepared_mime == "image/jpeg" else None,
            )
    except Exception as e:
        if isinstance(e, FileNotFoundError):
            raise
        raise ValueError("Invalid image") from e


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
