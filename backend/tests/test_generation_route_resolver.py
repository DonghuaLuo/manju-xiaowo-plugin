from __future__ import annotations

from typing import Any

import pytest

from lib.config.resolver import ProviderModel
from server.services.generation_route_resolver import (
    default_generation_profiles,
    is_video_resolution_below,
    resolve_generation_route,
    should_resolve_generation_route,
)


class _FakeResolver:
    def __init__(self, video_caps: dict[str, Any] | None = None) -> None:
        self.image_payloads: list[dict[str, Any]] = []
        self.video_payloads: list[dict[str, Any]] = []
        self.video_caps = video_caps or {"supported_durations": [4, 6, 8]}

    async def resolve_image_backend(self, project, payload, *, capability):
        self.image_payloads.append(dict(payload or {}))
        raw = payload.get(f"image_provider_{capability}") or payload.get("image_provider")
        if raw and "/" in raw:
            provider, model = raw.split("/", 1)
            return ProviderModel(provider, model)
        return ProviderModel("openai", "gpt-image-2")

    async def resolve_video_backend(self, project, payload):
        self.video_payloads.append(dict(payload or {}))
        raw = payload.get("video_backend")
        if raw and "/" in raw:
            provider, model = raw.split("/", 1)
            return ProviderModel(provider, model)
        provider = payload.get("video_provider") or "ark"
        model = payload.get("video_model") or "seedance-1-0"
        return ProviderModel(provider, model)

    async def video_capabilities_for_model(self, provider_id, model_id, project):
        return self.video_caps

    async def video_generate_audio(self, project_name=None):
        return True


class _FailingCapsResolver(_FakeResolver):
    async def video_capabilities_for_model(self, provider_id, model_id, project):
        raise ValueError("supported_durations is empty")


@pytest.mark.asyncio
async def test_storyboard_draft_profile_resolves_image_route():
    project = {
        "generation_profiles": {
            "storyboard_draft": {
                "image_provider_t2i": "openai/gpt-image-2",
                "resolution": "1K",
            }
        }
    }
    resolver = _FakeResolver()

    route = await resolve_generation_route(
        project=project,
        payload={"quality": "draft", "prompt": "p"},
        task_kind="storyboard",
        capability="t2i",
        resolver=resolver,  # type: ignore[arg-type]
        project_name="demo",
    )

    assert route.profile_key == "storyboard_draft"
    assert route.resolution == "1K"
    assert (route.provider_id, route.model_id) == ("openai", "gpt-image-2")
    assert route.metadata["generation_route"]["resolution"] == "1K"


@pytest.mark.asyncio
async def test_payload_resolution_overrides_profile_resolution():
    project = {
        "generation_profiles": {
            "asset": {
                "image_provider_t2i": "openai/gpt-image-2",
                "resolution": "2K",
            }
        }
    }

    route = await resolve_generation_route(
        project=project,
        payload={"quality": "final", "resolution": "4K", "image_provider_t2i": "ark/custom-image"},
        task_kind="character",
        capability="t2i",
        resolver=_FakeResolver(),  # type: ignore[arg-type]
        project_name="demo",
    )

    assert route.profile_key == "asset"
    assert route.resolution == "4K"
    assert (route.provider_id, route.model_id) == ("ark", "custom-image")


@pytest.mark.asyncio
async def test_video_profile_translates_backend_and_runtime_options():
    project = {"generation_profiles": default_generation_profiles()}
    resolver = _FakeResolver()

    route = await resolve_generation_route(
        project=project,
        payload={"quality": "draft", "prompt": "p"},
        task_kind="video",
        resolver=resolver,  # type: ignore[arg-type]
        project_name="demo",
    )

    assert route.profile_key == "video_draft"
    assert route.resolution == "720p"
    assert route.duration_seconds == 4
    assert route.generate_audio is False
    assert route.service_tier == "default"
    assert route.supported_durations == [4, 6, 8]
    assert "duration_seconds" not in resolver.video_payloads[-1]


@pytest.mark.asyncio
async def test_shot_tier_applies_project_profile_override_and_metadata():
    project = {
        "generation_profiles": default_generation_profiles(),
        "shot_tier_profiles": {
            "S": {
                "retry_budget": 4,
                "profiles": {
                    "video_final": {
                        "resolution": "4K",
                        "service_tier": "priority",
                    }
                },
            }
        },
    }
    resolver = _FakeResolver({"supported_durations": [4, 6, 8], "resolutions": ["1080p", "4K"]})

    route = await resolve_generation_route(
        project=project,
        payload={"quality": "final", "shot_tier": "S", "prompt": "p"},
        task_kind="video",
        resolver=resolver,  # type: ignore[arg-type]
        project_name="demo",
    )

    assert route.shot_tier == "S"
    assert route.resolution == "4K"
    assert route.service_tier == "priority"
    assert route.shot_tier_strategy["retry_budget"] == 4
    assert route.metadata["shot_tier"] == "S"
    assert route.metadata["generation_route"]["shot_tier_strategy"]["retry_budget"] == 4


@pytest.mark.asyncio
async def test_shot_level_tasks_default_to_a_tier_when_missing():
    project = {"generation_profiles": default_generation_profiles()}

    route = await resolve_generation_route(
        project=project,
        payload={"quality": "draft", "prompt": "p"},
        task_kind="storyboard",
        capability="t2i",
        resolver=_FakeResolver(),  # type: ignore[arg-type]
        project_name="demo",
    )

    assert route.shot_tier == "A"
    assert route.shot_tier_strategy["retry_budget"] == 1
    assert route.metadata["shot_tier"] == "A"
    assert route.metadata["generation_route"]["shot_tier"] == "A"


@pytest.mark.asyncio
async def test_video_draft_duration_follows_project_or_payload_duration():
    project = {"generation_profiles": default_generation_profiles(), "default_duration": 6}
    resolver = _FakeResolver()

    route = await resolve_generation_route(
        project=project,
        payload={"quality": "draft", "prompt": "p"},
        task_kind="video",
        resolver=resolver,  # type: ignore[arg-type]
        project_name="demo",
    )

    assert route.duration_seconds == 6

    route = await resolve_generation_route(
        project=project,
        payload={"quality": "draft", "prompt": "p", "duration_seconds": 8},
        task_kind="video",
        resolver=resolver,  # type: ignore[arg-type]
        project_name="demo",
    )

    assert route.duration_seconds == 8


@pytest.mark.asyncio
async def test_video_profile_constrains_duration_options_by_resolution():
    project = {"generation_profiles": default_generation_profiles()}
    resolver = _FakeResolver(
        {
            "supported_durations": [4, 6, 8],
            "duration_resolution_constraints": {"1080p": [8]},
        }
    )

    route = await resolve_generation_route(
        project=project,
        payload={"quality": "final", "prompt": "p"},
        task_kind="video",
        resolver=resolver,  # type: ignore[arg-type]
        project_name="demo",
    )

    assert route.profile_key == "video_final"
    assert route.resolution == "1080p"
    assert route.duration_seconds == 8
    assert route.supported_durations == [8]
    assert route.duration_resolution_constraints == {"1080p": [8]}
    assert route.metadata["generation_route"]["supported_durations"] == [8]
    assert route.metadata["generation_route"]["duration_resolution_constraints"] == {"1080p": [8]}


@pytest.mark.asyncio
async def test_video_profile_coerces_resolution_to_model_capability():
    project = {"generation_profiles": default_generation_profiles()}
    resolver = _FakeResolver(
        {
            "supported_durations": [1, 2, 3],
            "resolutions": ["480p", "720p"],
        }
    )

    route = await resolve_generation_route(
        project=project,
        payload={"quality": "final", "prompt": "p"},
        task_kind="video",
        resolver=resolver,  # type: ignore[arg-type]
        project_name="demo",
    )

    assert route.resolution == "720p"
    assert route.metadata["generation_route_warnings"][0]["key"] == "video_resolution_adjusted"


@pytest.mark.asyncio
async def test_video_profile_warns_when_capabilities_are_unavailable():
    project = {"generation_profiles": default_generation_profiles()}

    route = await resolve_generation_route(
        project=project,
        payload={"quality": "draft", "prompt": "p"},
        task_kind="video",
        resolver=_FailingCapsResolver(),  # type: ignore[arg-type]
        project_name="demo",
    )

    assert route.warnings[0]["key"] == "video_capabilities_unavailable"
    assert route.metadata["generation_route_warnings"][0]["params"]["reason"] == "supported_durations is empty"


@pytest.mark.asyncio
async def test_video_profile_coerces_explicit_duration_to_resolution_options():
    project = {"generation_profiles": default_generation_profiles()}
    resolver = _FakeResolver(
        {
            "supported_durations": [4, 6, 8],
            "duration_resolution_constraints": {"1080p": [8]},
        }
    )

    route = await resolve_generation_route(
        project=project,
        payload={"quality": "final", "prompt": "p", "duration_seconds": 6},
        task_kind="video",
        resolver=resolver,  # type: ignore[arg-type]
        project_name="demo",
    )

    assert route.duration_seconds == 8
    assert route.supported_durations == [8]
    assert route.metadata["generation_route_warnings"][0]["key"] == "video_duration_adjusted"


@pytest.mark.asyncio
async def test_profiles_opt_in_uses_task_default_quality_without_payload_quality():
    project = {"generation_profiles": default_generation_profiles()}

    route = await resolve_generation_route(
        project=project,
        payload={"prompt": "p"},
        task_kind="storyboard",
        capability="t2i",
        resolver=_FakeResolver(),  # type: ignore[arg-type]
        project_name="demo",
    )

    assert route.quality == "draft"
    assert route.profile_key == "storyboard_draft"
    assert route.resolution == "1K"


@pytest.mark.asyncio
async def test_grid_always_uses_grid_profile_as_final_quality():
    project = {"generation_profiles": default_generation_profiles()}

    route = await resolve_generation_route(
        project=project,
        payload={"quality": "draft", "prompt": "p"},
        task_kind="grid",
        capability="t2i",
        resolver=_FakeResolver(),  # type: ignore[arg-type]
        project_name="demo",
    )

    assert route.quality == "final"
    assert route.profile_key == "grid"
    assert route.resolution == "2K"
    assert route.metadata["generation_profile_key"] == "grid"


@pytest.mark.asyncio
async def test_reference_video_profile_resolves_draft_video_route():
    project = {"generation_profiles": default_generation_profiles()}

    route = await resolve_generation_route(
        project=project,
        payload={"quality": "draft", "prompt": "p"},
        task_kind="reference_video",
        resolver=_FakeResolver(),  # type: ignore[arg-type]
        project_name="demo",
    )

    assert route.profile_key == "reference_video_draft"
    assert route.resolution == "720p"
    assert route.duration_seconds is None
    assert route.generate_audio is False
    assert route.metadata["generation_route"]["task_kind"] == "reference_video"


@pytest.mark.asyncio
async def test_reference_video_route_rejects_models_without_reference_images():
    project = {"generation_profiles": default_generation_profiles()}
    resolver = _FakeResolver({"supported_durations": [4, 8], "max_reference_images": 0})

    with pytest.raises(ValueError, match="supports 0 reference images"):
        await resolve_generation_route(
            project=project,
            payload={"quality": "final", "prompt": "p"},
            task_kind="reference_video",
            resolver=resolver,  # type: ignore[arg-type]
            project_name="demo",
        )


def test_should_resolve_generation_route_only_for_new_inputs():
    assert should_resolve_generation_route({}, {"prompt": "p"}) is False
    assert should_resolve_generation_route({}, {"prompt": "p", "quality": "draft"}) is True
    assert should_resolve_generation_route({}, {"prompt": "p", "shot_tier": "S"}) is True
    assert should_resolve_generation_route({"generation_profiles": {}}, {"prompt": "p"}) is True


def test_video_resolution_below_compares_rank_not_equality():
    assert is_video_resolution_below("720p", "1080p") is True
    assert is_video_resolution_below("4K", "1080p") is False
    assert is_video_resolution_below("1080p", "1080p") is False
    assert is_video_resolution_below("weird", "1080p") is False
