from pathlib import Path

import pytest
from PIL import Image

from lib.image_backends.base import ImageCapability, ImageGenerationResult
from lib.media_generator import MediaGenerator
from lib.video_backends.base import VideoCapabilities


class _FakeImageBackend:
    """Fake ImageBackend conforming to the protocol."""

    name = "fake-image"
    model = "img-model"
    capabilities = {ImageCapability.TEXT_TO_IMAGE, ImageCapability.IMAGE_TO_IMAGE}

    def __init__(self):
        self.calls = []

    async def generate(self, request):
        self.calls.append(request)
        # Touch the output file so version tracking works
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        request.output_path.write_bytes(b"fake-image-data")
        return ImageGenerationResult(
            image_path=request.output_path,
            provider=self.name,
            model=self.model,
            usage_tokens=8,
        )


class _FakeVideoResult:
    def __init__(self):
        self.video_uri = "video-uri"
        self.usage_tokens = 0
        self.generate_audio = True


class _FakeVideoBackend:
    """Fake VideoBackend conforming to the protocol."""

    name = "fake-video"
    model = "video-model"

    def __init__(self):
        self.calls = []
        self._video_capabilities = VideoCapabilities(
            first_frame=True,
            last_frame=False,
            reference_images=True,
            max_reference_images=2,
        )

    @property
    def video_capabilities(self):
        return self._video_capabilities

    async def generate(self, request):
        self.calls.append(request)
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        request.output_path.write_bytes(b"fake-video-data")
        return _FakeVideoResult()


class _FakeVersions:
    def __init__(self):
        self.ensure_calls = []
        self.add_calls = []

    def ensure_current_tracked(self, **kwargs):
        self.ensure_calls.append(kwargs)

    def add_version(self, **kwargs):
        self.add_calls.append(kwargs)
        return len(self.add_calls)

    def get_versions(self, resource_type, resource_id):
        return {
            "current_version": len(self.add_calls),
            "versions": [{"created_at": "2026-01-01T00:00:00Z"}] * max(1, len(self.add_calls)),
        }


class _FakeUsage:
    def __init__(self):
        self.started = []
        self.finished = []

    async def start_call(self, **kwargs):
        self.started.append(kwargs)
        return len(self.started)

    async def finish_call(self, **kwargs):
        self.finished.append(kwargs)


class _FakeConfigResolver:
    """Fake ConfigResolver，返回可控的配置值。"""

    def __init__(self, video_generate_audio: bool = False):
        self._video_generate_audio = video_generate_audio

    async def video_generate_audio(self, project_name=None):
        return self._video_generate_audio


def _build_generator(tmp_path: Path) -> MediaGenerator:
    gen = object.__new__(MediaGenerator)
    gen.project_path = tmp_path / "projects" / "demo"
    gen.project_path.mkdir(parents=True, exist_ok=True)
    gen.project_name = "demo"
    gen._rate_limiter = None
    gen._image_backend = _FakeImageBackend()
    gen._video_backend = _FakeVideoBackend()
    gen._user_id = "default"
    gen._config = _FakeConfigResolver()
    gen.versions = _FakeVersions()
    gen.usage_tracker = _FakeUsage()
    return gen


class TestMediaGenerator:
    def test_get_output_path_and_invalid_type(self, tmp_path):
        gen = _build_generator(tmp_path)
        assert gen._get_output_path("storyboards", "E1S01").name == "scene_E1S01.png"
        assert gen._get_output_path("videos", "E1S01").name == "scene_E1S01.mp4"
        assert gen._get_output_path("characters", "Alice").name == "Alice.png"
        assert gen._get_output_path("reference_videos", "E1U1").name == "E1U1.mp4"
        with pytest.raises(ValueError):
            gen._get_output_path("bad", "x")

    def test_generate_image_success_and_failure(self, tmp_path):
        gen = _build_generator(tmp_path)
        output_path, version = gen.generate_image(
            prompt="p",
            resource_type="storyboards",
            resource_id="E1S01",
            aspect_ratio="9:16",
        )

        assert output_path.name == "scene_E1S01.png"
        assert version == 1
        assert gen.usage_tracker.started[0]["call_type"] == "image"
        assert gen.usage_tracker.finished[0]["status"] == "success"
        assert gen.usage_tracker.finished[0]["usage_tokens"] == 8

        async def _raise(request):
            raise RuntimeError("boom")

        gen._image_backend.generate = _raise
        with pytest.raises(RuntimeError):
            gen.generate_image(prompt="p", resource_type="characters", resource_id="A")

        assert any(item["status"] == "failed" for item in gen.usage_tracker.finished)

    @pytest.mark.asyncio
    async def test_generate_video_sync_and_async(self, tmp_path):
        gen = _build_generator(tmp_path)

        video_path, version, video_ref, video_uri = gen.generate_video(
            prompt="p",
            resource_type="videos",
            resource_id="E1S01",
            duration_seconds="bad",
        )
        assert video_path.name == "scene_E1S01.mp4"
        assert version == 1
        assert video_ref is None
        assert video_uri == "video-uri"

        video_path2, version2, _, _ = await gen.generate_video_async(
            prompt="p",
            resource_type="videos",
            resource_id="E1S02",
            duration_seconds="6",
        )
        assert video_path2.name == "scene_E1S02.mp4"
        assert version2 == 2
        assert gen.usage_tracker.started[-1]["call_type"] == "video"

    @pytest.mark.asyncio
    async def test_video_generate_audio_from_config_resolver(self, tmp_path):
        """验证 generate_video_async 通过 ConfigResolver 获取 audio 设置。"""
        gen = _build_generator(tmp_path)
        gen._config = _FakeConfigResolver(video_generate_audio=False)

        await gen.generate_video_async(
            prompt="p",
            resource_type="videos",
            resource_id="E1S03",
        )
        # VideoBackend 路径尊重 ConfigResolver 返回的值
        assert gen.usage_tracker.started[-1]["generate_audio"] is False

    @pytest.mark.asyncio
    async def test_video_generate_audio_respects_config_true(self, tmp_path):
        """验证 video_backend 尊重 ConfigResolver 返回的 True。"""
        gen = _build_generator(tmp_path)
        gen._config = _FakeConfigResolver(video_generate_audio=True)

        await gen.generate_video_async(
            prompt="p",
            resource_type="videos",
            resource_id="E1S04",
        )
        assert gen.usage_tracker.started[-1]["generate_audio"] is True

    @pytest.mark.asyncio
    async def test_video_generate_audio_defaults_true_when_config_none(self, tmp_path):
        """当 self._config is None 时，fallback 默认 True，
        与 ConfigResolver._DEFAULT_VIDEO_GENERATE_AUDIO 对齐（PR7 §11）。"""
        gen = _build_generator(tmp_path)
        gen._config = None

        await gen.generate_video_async(
            prompt="p",
            resource_type="videos",
            resource_id="E1S05",
        )
        assert gen.usage_tracker.started[-1]["generate_audio"] is True

    @pytest.mark.asyncio
    async def test_video_start_image_is_prepared_for_provider_without_mutating_source(self, tmp_path):
        gen = _build_generator(tmp_path)
        source = tmp_path / "storyboard.png"
        Image.new("RGB", (3200, 1800), color="purple").save(source, format="PNG")
        source_bytes = source.read_bytes()

        await gen.generate_video_async(
            prompt="p",
            resource_type="videos",
            resource_id="E1S06",
            start_image=source,
        )

        request = gen._video_backend.calls[-1]
        assert request.start_image is not None
        assert request.start_image != source
        assert not request.start_image.exists()
        assert request.start_image.suffix == ".jpg"
        assert source.read_bytes() == source_bytes
        metadata = gen.versions.add_calls[-1]["provider_input_images"]["start_image"]
        assert metadata["source_mime"] == "image/png"
        assert metadata["input_mime"] == "image/jpeg"
        assert metadata["resized"] is True
        assert gen.versions.add_calls[-1]["provider_input_payload"]["cleaned_up"] == 1

    @pytest.mark.asyncio
    async def test_video_provider_input_is_retained_on_failure_for_diagnostics(self, tmp_path, monkeypatch):
        gen = _build_generator(tmp_path)
        source = tmp_path / "storyboard.png"
        Image.new("RGB", (3200, 1800), color="purple").save(source, format="PNG")
        diagnostics: list[dict] = []

        class _FakeQueue:
            async def persist_api_call_id(self, task_id, call_id):
                assert task_id == "task-1"
                assert call_id == 1

            async def append_task_diagnostic(self, task_id, data):
                assert task_id == "task-1"
                diagnostics.append(data)

        monkeypatch.setattr("lib.generation_queue.get_generation_queue", lambda: _FakeQueue())

        async def fail(request):
            gen._video_backend.calls.append(request)
            raise RuntimeError("provider failed")

        gen._video_backend.generate = fail

        with pytest.raises(RuntimeError, match="provider failed"):
            await gen.generate_video_async(
                prompt="p",
                resource_type="videos",
                resource_id="E1S07",
                start_image=source,
                task_id="task-1",
            )

        request = gen._video_backend.calls[-1]
        assert request.start_image is not None
        assert request.start_image != source
        assert request.start_image.exists()
        assert gen.usage_tracker.finished[-1]["status"] == "failed"
        assert [d["diagnostic_type"] for d in diagnostics] == [
            "provider_input_prepared",
            "provider_input_retained_on_failure",
        ]
        retained = diagnostics[-1]["provider_input_payload"]
        assert retained["retained_on_failure"] is True
        assert retained["cleaned_up"] == 0
        assert diagnostics[-1]["provider_input_images"]["start_image"]["input_path"] == str(request.start_image)

    @pytest.mark.asyncio
    async def test_video_reference_images_are_truncated_and_audited(self, tmp_path):
        gen = _build_generator(tmp_path)
        refs = []
        for index in range(3):
            path = tmp_path / f"ref-{index}.png"
            Image.new("RGB", (64, 64), color="purple").save(path, format="PNG")
            refs.append(path)

        await gen.generate_video_async(
            prompt="p",
            resource_type="videos",
            resource_id="E1S08",
            reference_images=refs,
        )

        request = gen._video_backend.calls[-1]
        assert request.reference_images is not None
        assert len(request.reference_images) == 2
        metadata = gen.versions.add_calls[-1]["provider_reference_policy"]
        assert metadata["original_reference_image_count"] == 3
        assert metadata["submitted_reference_image_count"] == 2
        assert metadata["dropped_reference_image_count"] == 1
        assert metadata["reason"] == "provider_max_reference_images"

    @pytest.mark.asyncio
    async def test_reference_video_fails_when_backend_drops_all_reference_images(self, tmp_path):
        gen = _build_generator(tmp_path)
        gen._video_backend._video_capabilities = VideoCapabilities(
            first_frame=True,
            reference_images=False,
            max_reference_images=0,
        )
        ref = tmp_path / "ref.png"
        Image.new("RGB", (64, 64), color="purple").save(ref, format="PNG")

        with pytest.raises(ValueError, match="不支持参考图输入"):
            await gen.generate_video_async(
                prompt="p",
                resource_type="reference_videos",
                resource_id="E1U1",
                reference_images=[ref],
            )

        assert gen._video_backend.calls == []
        assert gen.usage_tracker.finished[-1]["status"] == "failed"
        assert gen.versions.add_calls == []
