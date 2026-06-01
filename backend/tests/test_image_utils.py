# tests/test_image_utils.py
"""image_utils 单元测试。"""

from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from lib.image_utils import compress_image_bytes, detect_image_mime, estimate_base64_size, prepare_provider_image_input


class TestCompressImageBytes:
    """compress_image_bytes 测试。"""

    def _make_png(self, width: int, height: int) -> bytes:
        """生成指定尺寸的 PNG 字节。"""
        img = Image.new("RGB", (width, height), color="red")
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def test_small_image_unchanged_dimensions(self):
        """小图（长边 < 2048）不缩放，但仍转为 JPEG。"""
        raw = self._make_png(800, 600)
        result = compress_image_bytes(raw)
        img = Image.open(BytesIO(result))
        assert img.format == "JPEG"
        assert img.size == (800, 600)

    def test_large_image_resized(self):
        """大图（长边 > 2048）缩放到长边 2048。"""
        raw = self._make_png(4096, 3072)
        result = compress_image_bytes(raw)
        img = Image.open(BytesIO(result))
        assert img.format == "JPEG"
        assert max(img.size) == 2048
        assert img.size == (2048, 1536)

    def test_portrait_large_image(self):
        """竖图大图也正确缩放。"""
        raw = self._make_png(2000, 4000)
        result = compress_image_bytes(raw)
        img = Image.open(BytesIO(result))
        assert max(img.size) == 2048
        assert img.size == (1024, 2048)

    def test_rgba_converted_to_rgb(self):
        """RGBA 图片转为 RGB（JPEG 不支持 alpha）。"""
        img = Image.new("RGBA", (100, 100), color=(255, 0, 0, 128))
        buf = BytesIO()
        img.save(buf, format="PNG")
        result = compress_image_bytes(buf.getvalue())
        out = Image.open(BytesIO(result))
        assert out.mode == "RGB"

    def test_jpeg_input(self):
        """JPEG 输入也能正常处理。"""
        img = Image.new("RGB", (500, 500), color="blue")
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=95)
        result = compress_image_bytes(buf.getvalue())
        out = Image.open(BytesIO(result))
        assert out.format == "JPEG"

    def test_webp_input(self):
        """WebP 输入也能正常处理。"""
        img = Image.new("RGB", (500, 500), color="green")
        buf = BytesIO()
        img.save(buf, format="WEBP")
        result = compress_image_bytes(buf.getvalue())
        out = Image.open(BytesIO(result))
        assert out.format == "JPEG"

    def test_invalid_input_raises(self):
        """非图片字节抛出 ValueError。"""
        with pytest.raises(ValueError, match="Invalid image"):
            compress_image_bytes(b"not an image")

    def test_output_smaller_than_input(self):
        """压缩后体积应显著减小。"""
        raw = self._make_png(3000, 2000)
        result = compress_image_bytes(raw)
        assert len(result) < len(raw)

    def test_detect_image_mime_uses_real_content(self, tmp_path):
        """真实 MIME 不依赖后缀，避免供应商 data URI 写错类型。"""
        img = Image.new("RGB", (320, 240), color="blue")
        source = tmp_path / "misnamed.png"
        img.save(source, format="JPEG")

        assert detect_image_mime(source) == "image/jpeg"

    def test_prepare_provider_image_input_keeps_source_and_records_metadata(self, tmp_path):
        img = Image.new("RGB", (3200, 1800), color="green")
        source = tmp_path / "master.png"
        img.save(source, format="PNG")
        source_bytes = source.read_bytes()

        prepared = prepare_provider_image_input(
            source,
            temp_dir=tmp_path / "provider-input",
            purpose="video-start",
            max_long_edge=1024,
        )

        assert source.read_bytes() == source_bytes
        assert prepared.path != source
        assert prepared.path.exists()
        assert prepared.prepared_mime == "image/jpeg"
        assert prepared.resized is True
        assert max(prepared.prepared_width, prepared.prepared_height) == 1024
        assert prepared.to_metadata()["estimated_base64_bytes"] == estimate_base64_size(prepared.prepared_bytes)

    def test_prepare_provider_image_input_preserves_alpha_as_png(self, tmp_path):
        img = Image.new("RGBA", (200, 200), color=(255, 0, 0, 128))
        source = tmp_path / "alpha.png"
        img.save(source, format="PNG")

        prepared = prepare_provider_image_input(source, temp_dir=tmp_path / "provider-input")

        assert prepared.prepared_mime == "image/png"
        assert prepared.path.suffix == ".png"
