import json


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_quality_metrics_upserts_rating_and_groups_stats(tmp_path):
    from lib.project_manager import ProjectManager
    from server.services.quality_metrics import QualityMetricsService

    project_dir = tmp_path / "projects" / "demo"
    _write_json(
        project_dir / "project.json",
        {"title": "测试项目", "content_mode": "narration", "episodes": []},
    )
    _write_json(
        project_dir / "versions" / "versions.json",
        {
            "videos": {
                "S1": {
                    "current_version": 1,
                    "versions": [
                        {
                            "version": 1,
                            "generation_quality": "final",
                            "shot_tier": "S",
                            "generation_route": {
                                "provider": "ark",
                                "model": "seedance",
                                "resolution": "1080p",
                            },
                        }
                    ],
                }
            }
        },
    )

    service = QualityMetricsService(ProjectManager(tmp_path / "projects"))
    result = service.upsert_rating(
        project_name="demo",
        resource_type="videos",
        resource_id="S1",
        version=1,
        rating=5,
        user_id="u1",
        dimensions={"character_consistency": 5, "motion_naturalness": 4},
    )
    assert result["rating"]["provider"] == "ark"
    assert result["rating"]["model"] == "seedance"
    assert result["rating"]["shot_tier"] == "S"

    service.upsert_rating(
        project_name="demo",
        resource_type="videos",
        resource_id="S1",
        version=1,
        rating=4,
        user_id="u1",
        dimensions={"character_consistency": 3, "bad": 8},
    )
    stats = service.get_stats(project_name="demo")
    ratings = service.list_ratings(project_name="demo", resource_type="videos", resource_id="S1", version=1)

    assert stats["count"] == 1
    assert stats["average_rating"] == 4
    assert stats["dimension_averages"] == [{"key": "character_consistency", "count": 1, "average_rating": 3}]
    assert stats["groups"]["provider"][0] == {"key": "ark", "count": 1, "average_rating": 4}
    assert ratings["ratings"][0]["rating"] == 4
    assert ratings["ratings"][0]["dimensions"] == {"character_consistency": 3}
