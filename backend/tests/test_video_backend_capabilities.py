from pathlib import Path
from unittest.mock import patch

from lib.video_backends.base import VideoCapabilities, VideoGenerationRequest


class TestVideoCapabilities:
    def test_defaults(self):
        caps = VideoCapabilities()
        assert caps.first_frame is True
        assert caps.last_frame is False
        assert caps.reference_images is False
        assert caps.max_reference_images == 0

    def test_first_last(self):
        caps = VideoCapabilities(last_frame=True)
        assert caps.last_frame is True

    def test_custom_values(self):
        caps = VideoCapabilities(last_frame=True, reference_images=True, max_reference_images=9)
        assert caps.last_frame is True
        assert caps.reference_images is True
        assert caps.max_reference_images == 9


class TestVideoCapabilitiesForModel:
    def test_ark_static_caps_preserve_model_specific_rules(self):
        from lib.video_backends.ark import ArkVideoBackend

        assert ArkVideoBackend.video_capabilities_for_model("doubao-seedance-2-0").max_reference_images == 9
        fast = ArkVideoBackend.video_capabilities_for_model("doubao-seedance-1-0-pro-fast-251015")
        assert fast.last_frame is False
        assert fast.reference_images is False
        pro = ArkVideoBackend.video_capabilities_for_model("doubao-seedance-1-0-pro-250528")
        assert pro.last_frame is True
        assert pro.reference_images is False

    def test_ark_property_delegates_to_static_caps(self):
        from lib.video_backends.ark import ArkVideoBackend

        with patch("lib.video_backends.ark.create_ark_client", return_value=object()):
            backend = ArkVideoBackend(api_key="k", model="doubao-seedance-2-0", base_url="https://ark.example")
        assert backend.video_capabilities == ArkVideoBackend.video_capabilities_for_model(backend.model)

    def test_v2_static_and_property_caps(self):
        from lib.video_backends.v2_video_generations import V2VideoGenerationsBackend

        caps = V2VideoGenerationsBackend.video_capabilities_for_model("any-model")
        assert caps.first_frame and caps.last_frame and caps.reference_images
        assert caps.max_reference_images == 4
        backend = V2VideoGenerationsBackend(api_key="k", base_url="https://api.example", model="any-model")
        assert backend.video_capabilities == caps

    def test_vidu_static_and_property_caps(self):
        from lib.video_backends.vidu import ViduVideoBackend

        caps = ViduVideoBackend.video_capabilities_for_model("viduq3-turbo")
        assert caps.first_frame and caps.last_frame and caps.reference_images
        assert caps.max_reference_images == 7
        backend = ViduVideoBackend(api_key="k", model="viduq3-turbo", base_url="https://vidu.example")
        assert backend.video_capabilities == caps


class TestVideoGenerationRequestNewFields:
    def test_end_image_default_none(self):
        req = VideoGenerationRequest(prompt="t", output_path=Path("/tmp/o.mp4"))
        assert req.end_image is None
        assert req.reference_images is None

    def test_end_image_set(self):
        req = VideoGenerationRequest(
            prompt="t",
            output_path=Path("/tmp/o.mp4"),
            start_image=Path("/tmp/f.png"),
            end_image=Path("/tmp/l.png"),
        )
        assert req.end_image == Path("/tmp/l.png")

    def test_reference_images(self):
        req = VideoGenerationRequest(
            prompt="t",
            output_path=Path("/tmp/o.mp4"),
            reference_images=[Path("/tmp/r1.png"), Path("/tmp/r2.png")],
        )
        assert len(req.reference_images) == 2

    def test_existing_fields_unchanged(self):
        """Ensure existing fields still work as before."""
        req = VideoGenerationRequest(
            prompt="test prompt",
            output_path=Path("/tmp/out.mp4"),
            aspect_ratio="16:9",
            duration_seconds=5,
            resolution="720p",
            start_image=Path("/tmp/start.png"),
            generate_audio=False,
            project_name="my_project",
            service_tier="flex",
            seed=42,
        )
        assert req.prompt == "test prompt"
        assert req.start_image == Path("/tmp/start.png")
        assert req.generate_audio is False
        assert req.seed == 42
