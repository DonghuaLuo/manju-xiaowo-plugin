"""基本路由存在性测试：验证 grids router 注册了预期路径。"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from lib.grid.models import GridGeneration
from lib.grid_manager import GridManager
from lib.script_editor import ScriptEditError
from server.auth import CurrentUserInfo, get_current_user
from server.routers import grids
from server.routers.grids import router


class _FakeQueue:
    def __init__(self, tasks_by_status=None):
        self.calls = []
        self.tasks_by_status = tasks_by_status or {}

    async def enqueue_task(self, **kwargs):
        self.calls.append(kwargs)
        return {"task_id": f"task-{len(self.calls)}", "deduped": False}

    async def list_tasks(
        self,
        *,
        project_name=None,
        status=None,
        task_type=None,
        source=None,
        page=1,
        page_size=50,
    ):
        del project_name, task_type, source
        items = list(self.tasks_by_status.get(status, []))
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "items": items[start:end],
            "total": len(items),
            "page": page,
            "page_size": page_size,
        }


class _FakePM:
    def __init__(self, project_path: Path, script_payload=None):
        self.project_path = project_path
        self.script_payload = script_payload

    def load_project(self, project_name):
        return {"style": "Anime", "aspect_ratio": "9:16"}

    def get_project_path(self, project_name):
        return self.project_path

    def load_script(self, project_name, script_file):
        if self.script_payload is not None:
            return self.script_payload
        raise ScriptEditError("segments 必须是列表，当前为 NoneType")


def _client(monkeypatch, fake_pm, fake_queue):
    monkeypatch.setattr(grids, "get_project_manager", lambda: fake_pm)
    monkeypatch.setattr(grids, "get_generation_queue", lambda: fake_queue)

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="default", sub="testuser", role="admin")
    app.include_router(grids.router, prefix="/api/v1")
    return TestClient(app)


def _script_payload(count: int) -> dict:
    return {
        "segments": [
            {
                "segment_id": f"SEG-{idx}",
                "text": f"scene {idx}",
                "image_prompt": f"image prompt {idx}",
                "segment_break": False,
            }
            for idx in range(1, count + 1)
        ]
    }


def _save_grid(
    project_path: Path,
    *,
    scene_ids: list[str],
    status: str = "completed",
    created_at: str | None = None,
) -> GridGeneration:
    gm = GridManager(project_path)
    grid = GridGeneration.create(
        episode=1,
        script_file="episode_1.json",
        scene_ids=scene_ids,
        rows=2,
        cols=2,
        grid_size="grid_4",
        provider="",
        model="",
    )
    grid.status = status
    grid.created_at = created_at or (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    gm.save(grid)
    return grid


class TestGridRouterExists:
    def test_router_has_routes(self):
        paths = [r.path for r in router.routes]
        assert any("generate/grid" in p for p in paths)
        assert any("/grids" in p for p in paths)

    def test_router_has_generate_grid_endpoint(self):
        paths = [r.path for r in router.routes]
        assert any("generate/grid/{episode}" in p for p in paths)

    def test_router_has_list_grids_endpoint(self):
        paths = [r.path for r in router.routes]
        assert any(p.endswith("/grids") for p in paths)

    def test_router_has_get_grid_endpoint(self):
        paths = [r.path for r in router.routes]
        assert any("/grids/{grid_id}" in p for p in paths)

    def test_router_has_regenerate_endpoint(self):
        paths = [r.path for r in router.routes]
        assert any("regenerate" in p for p in paths)

    def test_generate_grid_dirty_script_returns_400(self, tmp_path, monkeypatch):
        fake_pm = _FakePM(tmp_path / "projects" / "demo")
        fake_queue = _FakeQueue()
        client = _client(monkeypatch, fake_pm, fake_queue)

        with client:
            resp = client.post(
                "/api/v1/projects/demo/generate/grid/1",
                json={"script_file": "episode_1.json"},
            )

        assert resp.status_code == 400
        assert "segments 必须是列表" in resp.json()["detail"]
        assert fake_queue.calls == []

    def test_generate_grid_scene_ids_only_enqueues_matching_chunk_and_preserves_other_chunks(
        self,
        tmp_path,
        monkeypatch,
    ):
        project_path = tmp_path / "projects" / "demo"
        existing_grid = _save_grid(project_path, scene_ids=["SEG-1", "SEG-2", "SEG-3", "SEG-4"])
        fake_pm = _FakePM(project_path, script_payload=_script_payload(5))
        fake_queue = _FakeQueue()
        client = _client(monkeypatch, fake_pm, fake_queue)

        with client:
            resp = client.post(
                "/api/v1/projects/demo/generate/grid/1",
                json={"script_file": "episode_1.json", "scene_ids": ["SEG-5"]},
            )

        assert resp.status_code == 200
        assert resp.json()["grid_ids"]
        assert len(fake_queue.calls) == 1
        assert fake_queue.calls[0]["payload"]["scene_ids"] == ["SEG-5"]
        assert GridManager(project_path).get(existing_grid.id) is not None

    def test_list_grids_marks_in_progress_without_active_task_failed(self, tmp_path, monkeypatch):
        project_path = tmp_path / "projects" / "demo"
        stale_grid = _save_grid(project_path, scene_ids=["SEG-1"], status="generating")
        fake_pm = _FakePM(project_path)
        fake_queue = _FakeQueue()
        client = _client(monkeypatch, fake_pm, fake_queue)

        with client:
            resp = client.get("/api/v1/projects/demo/grids")

        assert resp.status_code == 200
        body = resp.json()
        assert body[0]["id"] == stale_grid.id
        assert body[0]["status"] == "failed"
        assert "生成任务已不存在" in body[0]["error_message"]

        saved_grid = GridManager(project_path).get(stale_grid.id)
        assert saved_grid is not None
        assert saved_grid.status == "failed"

    def test_get_grid_keeps_in_progress_with_active_task(self, tmp_path, monkeypatch):
        project_path = tmp_path / "projects" / "demo"
        active_grid = _save_grid(project_path, scene_ids=["SEG-1"], status="splitting")
        fake_pm = _FakePM(project_path)
        fake_queue = _FakeQueue(tasks_by_status={"running": [{"resource_id": active_grid.id}]})
        client = _client(monkeypatch, fake_pm, fake_queue)

        with client:
            resp = client.get(f"/api/v1/projects/demo/grids/{active_grid.id}")

        assert resp.status_code == 200
        assert resp.json()["status"] == "splitting"
        assert GridManager(project_path).get(active_grid.id).status == "splitting"

    def test_get_grid_keeps_recent_in_progress_without_task_during_enqueue_grace(self, tmp_path, monkeypatch):
        project_path = tmp_path / "projects" / "demo"
        recent_grid = _save_grid(
            project_path,
            scene_ids=["SEG-1"],
            status="pending",
            created_at=datetime.now(UTC).isoformat(),
        )
        fake_pm = _FakePM(project_path)
        fake_queue = _FakeQueue()
        client = _client(monkeypatch, fake_pm, fake_queue)

        with client:
            resp = client.get(f"/api/v1/projects/demo/grids/{recent_grid.id}")

        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"
        assert GridManager(project_path).get(recent_grid.id).status == "pending"
