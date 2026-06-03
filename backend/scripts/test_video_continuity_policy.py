from __future__ import annotations

from pathlib import Path
from typing import Any

from lib.video_backends.base import VideoCapabilities
from server.services import generation_tasks


class _FakeVideoBackend:
    name = "fake-video"
    model = "fake-model"

    def __init__(self, caps: VideoCapabilities) -> None:
        self.video_capabilities = caps


class _FakeGenerator:
    def __init__(self, caps: VideoCapabilities) -> None:
        self._video_backend = _FakeVideoBackend(caps)


def _project_path(tmp_path: Path) -> Path:
    project_path = tmp_path / "project"
    storyboard_dir = project_path / "storyboards"
    storyboard_dir.mkdir(parents=True)
    (storyboard_dir / "scene_E1S01.png").write_bytes(b"png")
    (storyboard_dir / "scene_E1S02.png").write_bytes(b"png")
    return project_path


def _items() -> list[dict[str, Any]]:
    return [
        {
            "segment_id": "E1S01",
            "transition_to_next": "cut",
            "scenes": ["hall"],
            "generated_assets": {"storyboard_image": "storyboards/scene_E1S01.png"},
        },
        {
            "segment_id": "E1S02",
            "segment_break": False,
            "scenes": ["hall"],
            "generated_assets": {"storyboard_image": "storyboards/scene_E1S02.png"},
        },
    ]


def _resolve(
    *,
    tmp_path: Path,
    caps: VideoCapabilities,
    policy: str = "auto",
) -> tuple[Path | None, list[Path] | None, dict[str, Any], Path]:
    project_path = _project_path(tmp_path)
    items = _items()
    end_image, reference_images, meta = generation_tasks._resolve_video_end_image(
        project={"video_continuity_policy": policy},
        project_path=project_path,
        items=items,
        id_field="segment_id",
        char_field="characters_in_segment",
        item_index=0,
        current_item=items[0],
        resource_id="E1S01",
        generator=_FakeGenerator(caps),
        payload={},
    )
    return end_image, reference_images, meta, project_path


def test_auto_uses_reference_assisted_only_when_reference_keeps_start_image(tmp_path: Path) -> None:
    caps = VideoCapabilities(
        first_frame=True,
        reference_images=True,
        reference_images_with_start_image=True,
        max_reference_images=7,
    )

    end_image, reference_images, meta, project_path = _resolve(tmp_path=tmp_path, caps=caps)

    next_storyboard = project_path / "storyboards" / "scene_E1S02.png"
    assert end_image is None
    assert reference_images == [next_storyboard]
    assert meta["effective_policy"] == "reference_assisted"
    assert meta["submitted_reference_images"] == [str(next_storyboard)]


def test_auto_stays_start_only_when_reference_would_drop_start_image(tmp_path: Path) -> None:
    caps = VideoCapabilities(
        first_frame=False,
        reference_images=True,
        max_reference_images=7,
    )

    end_image, reference_images, meta, _ = _resolve(tmp_path=tmp_path, caps=caps)

    assert end_image is None
    assert reference_images is None
    assert meta["effective_policy"] == "start_only"
    assert meta["skip_reason"] == "provider_no_reference_with_start_image"
    assert meta["provider_supports_reference_images"] is True
    assert meta["provider_supports_reference_with_start_image"] is False


def test_reference_assisted_policy_requires_reference_with_start_image(tmp_path: Path) -> None:
    caps = VideoCapabilities(
        first_frame=False,
        reference_images=True,
        max_reference_images=7,
    )

    end_image, reference_images, meta, _ = _resolve(
        tmp_path=tmp_path,
        caps=caps,
        policy="reference_assisted",
    )

    assert end_image is None
    assert reference_images is None
    assert meta["effective_policy"] == "start_only"
    assert meta["skip_reason"] == "provider_no_reference_with_start_image"
