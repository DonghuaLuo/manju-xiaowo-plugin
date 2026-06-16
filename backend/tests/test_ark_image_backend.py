"""Ark image backend regressions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

from lib.config.registry import PROVIDER_REGISTRY
from lib.image_backends.base import ImageGenerationRequest

_PNG_1X1_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


@dataclass
class _FakeImageData:
    b64_json: str = _PNG_1X1_B64


@dataclass
class _FakeImagesResponse:
    data: list[_FakeImageData]


def _make_client_mock() -> MagicMock:
    client = MagicMock()
    client.images.generate.return_value = _FakeImagesResponse(data=[_FakeImageData()])
    return client


async def _generate_with_size(tmp_path: Path, image_size: str) -> str:
    from lib.image_backends.ark import ArkImageBackend

    client = _make_client_mock()
    with patch("lib.image_backends.ark.create_ark_client", return_value=client):
        backend = ArkImageBackend(api_key="test-key")

    await backend.generate(ImageGenerationRequest(prompt="x", output_path=tmp_path / "out.png", image_size=image_size))
    return client.images.generate.call_args.kwargs["size"]


async def test_ark_seedream_normalizes_profile_tier_to_api_size(tmp_path: Path) -> None:
    assert await _generate_with_size(tmp_path, "2K") == "2k"


async def test_ark_seedream_coerces_unsupported_small_profile_size(tmp_path: Path) -> None:
    assert await _generate_with_size(tmp_path, "1K") == "2k"
    assert await _generate_with_size(tmp_path, "512px") == "2k"


async def test_ark_seedream_keeps_explicit_width_height(tmp_path: Path) -> None:
    assert await _generate_with_size(tmp_path, "2048*2048") == "2048x2048"


def test_ark_seedream_registry_declares_model_specific_resolutions() -> None:
    ark_models = PROVIDER_REGISTRY["ark"].models
    assert ark_models["doubao-seedream-5-0-lite-260128"].resolutions == ["2K", "3K", "4K"]
    assert ark_models["doubao-seedream-5-0-260128"].resolutions == ["2K", "3K", "4K"]
    assert ark_models["doubao-seedream-4-5-251128"].resolutions == ["2K", "4K"]
    assert ark_models["doubao-seedream-4-0-250828"].resolutions == ["1K", "2K", "4K"]
