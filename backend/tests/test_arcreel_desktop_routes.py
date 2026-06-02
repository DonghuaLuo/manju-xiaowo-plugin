import json

import pytest


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@pytest.mark.asyncio
async def test_desktop_resource_dispatch_supports_quality_ratings(tmp_path, monkeypatch):
    from lib.project_manager import ProjectManager
    from server.routers import quality as quality_router
    from utils import arcreel_desktop_routes

    project_root = tmp_path / "projects"
    project_dir = project_root / "demo"
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

    monkeypatch.setattr(quality_router, "pm", ProjectManager(project_root))
    monkeypatch.setattr(arcreel_desktop_routes, "_ROUTES", None)

    created = await arcreel_desktop_routes.dispatch_desktop_resource(
        {
            "operation": "create",
            "resource": "projects/demo/quality-ratings",
            "locale": "zh",
            "body": {
                "kind": "json",
                "value": {
                    "resource_type": "videos",
                    "resource_id": "S1",
                    "version": 1,
                    "rating": 5,
                    "dimensions": {"motion_naturalness": 4},
                },
            },
        }
    )

    assert created["success"] is True
    rating = created["content"]["value"]["rating"]
    assert rating["rating"] == 5
    assert rating["provider"] == "ark"

    listed = await arcreel_desktop_routes.dispatch_desktop_resource(
        {
            "operation": "read",
            "resource": "projects/demo/quality-ratings",
            "query": {
                "resource_type": ["videos"],
                "resource_id": ["S1"],
                "version": ["1"],
            },
        }
    )

    assert listed["success"] is True
    assert listed["content"]["value"]["ratings"][0]["rating"] == 5
