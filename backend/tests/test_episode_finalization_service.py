import json

import pytest


class FakeQueue:
    def __init__(self):
        self.calls = []

    async def enqueue_task(self, **kwargs):
        self.calls.append(kwargs)
        return {"task_id": f"task-{len(self.calls)}", "deduped": False}


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@pytest.mark.asyncio
async def test_finalize_episode_enqueues_final_storyboard_and_dependent_video(tmp_path):
    from lib.project_manager import ProjectManager
    from server.services.finalization import EpisodeFinalizationService

    pm = ProjectManager(tmp_path / "projects")
    project_dir = tmp_path / "projects" / "demo"
    (project_dir / "storyboards").mkdir(parents=True)
    (project_dir / "storyboards" / "scene_S1.png").write_bytes(b"fake")

    _write_json(
        project_dir / "project.json",
        {
            "title": "测试项目",
            "content_mode": "narration",
            "episodes": [{"episode": 1, "title": "第一集", "script_file": "scripts/episode_1.json"}],
            "generation_profiles": {
                "video_final": {"resolution": "1080p"},
            },
        },
    )
    _write_json(
        project_dir / "scripts" / "episode_1.json",
        {
            "content_mode": "narration",
            "segments": [
                {
                    "segment_id": "S1",
                    "duration_seconds": 8,
                    "image_prompt": {"scene": "山门前", "composition": {}},
                    "video_prompt": {"action": "镜头缓慢推进"},
                    "generated_assets": {"storyboard_image": "storyboards/scene_S1.png"},
                },
                {
                    "segment_id": "S2",
                    "duration_seconds": 6,
                    "image_prompt": {"scene": "古寺内", "composition": {}},
                    "video_prompt": {"action": "人物转身"},
                    "generated_assets": {},
                },
            ],
        },
    )
    _write_json(
        project_dir / "versions" / "versions.json",
        {
            "storyboards": {
                "S1": {"current_version": 1, "versions": [{"version": 1, "generation_quality": "final"}]}
            }
        },
    )

    queue = FakeQueue()
    service = EpisodeFinalizationService(pm, queue)
    result = await service.finalize_episode(project_name="demo", episode=1, user_id="u1")

    assert result["summary"]["storyboards_enqueued"] == 1
    assert result["summary"]["videos_enqueued"] == 2
    assert result["issues"] == []

    assert queue.calls[0]["task_type"] == "storyboard"
    assert queue.calls[0]["resource_id"] == "S2"
    assert queue.calls[0]["payload"]["quality"] == "final"

    assert queue.calls[1]["task_type"] == "video"
    assert queue.calls[1]["resource_id"] == "S1"
    assert queue.calls[1]["dependency_task_id"] is None
    assert queue.calls[1]["payload"]["quality"] == "final"
    assert queue.calls[1]["payload"]["duration_seconds"] == 8

    assert queue.calls[2]["task_type"] == "video"
    assert queue.calls[2]["resource_id"] == "S2"
    assert queue.calls[2]["dependency_task_id"] == "task-1"
    assert queue.calls[2]["payload"]["quality"] == "final"


@pytest.mark.asyncio
async def test_finalize_reference_video_episode_enqueues_final_units(tmp_path):
    from lib.project_manager import ProjectManager
    from server.services.finalization import EpisodeFinalizationService

    pm = ProjectManager(tmp_path / "projects")
    project_dir = tmp_path / "projects" / "demo"
    project_dir.mkdir(parents=True)
    _write_json(
        project_dir / "project.json",
        {
            "title": "测试项目",
            "content_mode": "drama",
            "generation_mode": "reference_video",
            "episodes": [
                {
                    "episode": 1,
                    "title": "第一集",
                    "script_file": "scripts/episode_1.json",
                    "generation_mode": "reference_video",
                }
            ],
        },
    )
    _write_json(
        project_dir / "scripts" / "episode_1.json",
        {
            "generation_mode": "reference_video",
            "video_units": [
                {
                    "unit_id": "U1",
                    "duration_seconds": 6,
                    "shots": [{"text": "人物推门", "duration": 6}],
                    "references": [],
                    "generated_assets": {},
                }
            ],
        },
    )

    queue = FakeQueue()
    service = EpisodeFinalizationService(pm, queue)
    result = await service.finalize_episode(project_name="demo", episode=1, user_id="u1")

    assert result["mode"] == "reference_video"
    assert result["summary"]["reference_videos_enqueued"] == 1
    assert queue.calls[0]["task_type"] == "reference_video"
    assert queue.calls[0]["resource_id"] == "U1"
    assert queue.calls[0]["payload"]["quality"] == "final"
    assert queue.calls[0]["payload"]["duration_seconds"] == 6


@pytest.mark.asyncio
async def test_finalize_episode_accepts_video_above_target_resolution(tmp_path):
    from lib.project_manager import ProjectManager
    from server.services.finalization import EpisodeFinalizationService

    pm = ProjectManager(tmp_path / "projects")
    project_dir = tmp_path / "projects" / "demo"
    (project_dir / "storyboards").mkdir(parents=True)
    (project_dir / "videos").mkdir()
    (project_dir / "storyboards" / "scene_S1.png").write_bytes(b"fake")
    (project_dir / "videos" / "segment_S1.mp4").write_bytes(b"fake")

    _write_json(
        project_dir / "project.json",
        {
            "title": "测试项目",
            "content_mode": "narration",
            "episodes": [{"episode": 1, "title": "第一集", "script_file": "scripts/episode_1.json"}],
            "generation_profiles": {"video_final": {"resolution": "1080p"}},
        },
    )
    _write_json(
        project_dir / "scripts" / "episode_1.json",
        {
            "content_mode": "narration",
            "segments": [
                {
                    "segment_id": "S1",
                    "duration_seconds": 8,
                    "image_prompt": {"scene": "山门前", "composition": {}},
                    "video_prompt": {"action": "镜头缓慢推进"},
                    "generated_assets": {
                        "storyboard_image": "storyboards/scene_S1.png",
                        "video_clip": "videos/segment_S1.mp4",
                    },
                }
            ],
        },
    )
    _write_json(
        project_dir / "versions" / "versions.json",
        {
            "storyboards": {
                "S1": {"current_version": 1, "versions": [{"version": 1, "generation_quality": "final"}]}
            },
            "videos": {
                "S1": {
                    "current_version": 1,
                    "versions": [
                        {
                            "version": 1,
                            "generation_quality": "final",
                            "source_storyboard_generation_quality": "final",
                            "generation_route": {"resolution": "4K"},
                        }
                    ],
                }
            },
        },
    )

    queue = FakeQueue()
    service = EpisodeFinalizationService(pm, queue)
    result = await service.finalize_episode(project_name="demo", episode=1, user_id="u1")

    assert result["summary"]["already_final"] == 1
    assert result["summary"]["videos_enqueued"] == 0
    assert queue.calls == []
