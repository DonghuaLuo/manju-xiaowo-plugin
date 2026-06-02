import pytest

from server.agent_runtime.sdk_tools import text_generation
from server.services.generation_route_resolver import GenerationRoute


@pytest.mark.asyncio
async def test_video_quality_recommendations_include_draft_and_final(monkeypatch):
    calls: list[tuple[str, str]] = []

    class FakeResolver:
        def __init__(self, *_args, **_kwargs):
            pass

    async def fake_resolve_generation_route(**kwargs):
        task_kind = kwargs["task_kind"]
        quality = kwargs["quality"]
        calls.append((task_kind, quality))
        return GenerationRoute(
            task_kind=task_kind,
            media_type="video",
            quality=quality,
            profile_key=f"{task_kind}_{quality}",
            provider_id="doubao",
            model_id="seedance",
            resolution="720p" if quality == "draft" else "1080p",
            duration_seconds=8 if task_kind == "video" else None,
            generate_audio=quality == "final",
            supported_resolutions=["720p", "1080p"],
            supported_durations=[8],
        )

    monkeypatch.setattr(text_generation, "ConfigResolver", FakeResolver)
    monkeypatch.setattr(text_generation, "resolve_generation_route", fake_resolve_generation_route)

    recommendations = await text_generation._build_video_quality_recommendations(
        project_name="demo",
        project={"generation_profiles": {}},
    )

    assert calls == [
        ("video", "draft"),
        ("video", "final"),
        ("reference_video", "draft"),
        ("reference_video", "final"),
    ]
    assert recommendations["video"]["draft"]["resolution"] == "720p"
    assert recommendations["video"]["final"]["resolution"] == "1080p"
    assert recommendations["video"]["final"]["generate_audio"] is True
    assert recommendations["reference_video"]["final"]["duration_seconds"] is None
