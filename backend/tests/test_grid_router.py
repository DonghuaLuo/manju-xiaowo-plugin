"""基本路由存在性测试：验证 grids router 注册了预期路径。"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from lib.script_editor import ScriptEditError
from server.auth import CurrentUserInfo, get_current_user
from server.routers import grids
from server.routers.grids import router


class _FakeQueue:
    def __init__(self):
        self.calls = []

    async def enqueue_task(self, **kwargs):
        self.calls.append(kwargs)
        return {"task_id": f"task-{len(self.calls)}", "deduped": False}


class _FakePM:
    def __init__(self, project_path: Path):
        self.project_path = project_path

    def load_project(self, project_name):
        return {"style": "Anime", "aspect_ratio": "9:16"}

    def get_project_path(self, project_name):
        return self.project_path

    def load_script(self, project_name, script_file):
        raise ScriptEditError("segments 必须是列表，当前为 NoneType")


def _client(monkeypatch, fake_pm, fake_queue):
    monkeypatch.setattr(grids, "get_project_manager", lambda: fake_pm)
    monkeypatch.setattr(grids, "get_generation_queue", lambda: fake_queue)

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="default", sub="testuser", role="admin")
    app.include_router(grids.router, prefix="/api/v1")
    return TestClient(app)


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
