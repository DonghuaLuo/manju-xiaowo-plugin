import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from lib.prompt_utils import VideoPromptPolicy
from lib.script_editor import ScriptEditError
from lib.version_manager import VersionManager
from server.auth import CurrentUserInfo, get_current_user
from server.routers import versions


class _FakePM:
    def __init__(self):
        self.updated = []

    def get_project_path(self, project_name):
        from pathlib import Path

        return Path("/tmp") / project_name

    def _update_asset_sheet(self, asset_type, *args):
        self.updated.append((asset_type, args))

    def update_scene_asset(self, *args, **kwargs):
        self.updated.append(("storyboard", args, kwargs))


class _FakeVM:
    def __init__(self, project_path=None):
        self.project_path = project_path

    def get_versions(self, resource_type, resource_id):
        if resource_type == "bad":
            raise ValueError("bad type")
        return {
            "current_version": 1,
            "versions": [{"version": 1, "file": f"versions/{resource_type}/{resource_id}.png"}],
        }

    def restore_version(self, resource_type, resource_id, version, current_file):
        if version == 404:
            raise FileNotFoundError("missing")
        if version == 400:
            raise ValueError("bad")
        return {
            "restored_version": version,
            "current_version": version,
            "prompt": "p",
        }


class _StoryboardSyncPM:
    def __init__(self, project_path):
        self.project_path = project_path
        self.update_calls = []

    def get_project_path(self, project_name):
        return self.project_path

    def update_scene_asset(self, project_name, script_filename, scene_id, asset_type, asset_path):
        self.update_calls.append(script_filename)
        if script_filename == "a.json":
            raise KeyError("missing scene")
        if script_filename == "b.json":
            raise ScriptEditError("bad script")


class _DesignDeletePM:
    def __init__(self, project_path, project, scripts):
        self.project_path = project_path
        self.project = project
        self.scripts = scripts

    def get_project_path(self, project_name):
        return self.project_path

    def load_project(self, project_name):
        return self.project

    def list_scripts(self, project_name):
        return list(self.scripts)

    def load_script(self, project_name, filename):
        return self.scripts[filename]

    def update_project(self, project_name, mutate_fn):
        mutate_fn(self.project)
        return self.project


class _ExternalUploadPM:
    def __init__(self, project_path):
        self.project_path = project_path
        self.project = {"style": "", "default_duration": 5}
        self.script = {
            "episode": 1,
            "segments": [
                {
                    "segment_id": "E1S01",
                    "image_prompt": "image prompt",
                    "video_prompt": "video prompt",
                    "duration_seconds": 4,
                    "generated_assets": {},
                    "characters_in_segment": [],
                    "scenes": [],
                    "props": [],
                }
            ],
        }
        self.update_calls = []

    def get_project_path(self, project_name):
        return self.project_path

    def load_project(self, project_name):
        return self.project

    def load_script(self, project_name, filename):
        return self.script

    def update_scene_asset(self, project_name, script_filename, scene_id, asset_type, asset_path):
        self.update_calls.append((scene_id, asset_type, asset_path))
        self.script["segments"][0].setdefault("generated_assets", {})[asset_type] = asset_path


class _UnreadableUploadStream:
    def read(self, *args, **kwargs):
        raise AssertionError("video path upload should copy the local file path instead of reading the stream")

    def seek(self, *args, **kwargs):
        raise AssertionError("video path upload should not touch the upload stream")


def _client(monkeypatch):
    fake_pm = _FakePM()
    monkeypatch.setattr(versions, "get_project_manager", lambda: fake_pm)
    monkeypatch.setattr(versions, "get_version_manager", lambda project_name: _FakeVM())

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="default", sub="testuser", role="admin")
    app.include_router(versions.router, prefix="/api/v1")
    return TestClient(app), fake_pm


class TestVersionsRouter:
    def test_get_versions_and_restore(self, monkeypatch):
        client, fake_pm = _client(monkeypatch)
        with client:
            get_resp = client.get("/api/v1/projects/demo/versions/characters/Alice")
            assert get_resp.status_code == 200
            assert get_resp.json()["current_version"] == 1

            restore_resp = client.post("/api/v1/projects/demo/versions/characters/Alice/restore/1")
            assert restore_resp.status_code == 200
            assert restore_resp.json()["current_version"] == 1
            assert any(item[0] == "character" for item in fake_pm.updated)

    def test_get_and_restore_scenes(self, monkeypatch):
        client, fake_pm = _client(monkeypatch)
        with client:
            get_resp = client.get("/api/v1/projects/demo/versions/scenes/庙宇")
            assert get_resp.status_code == 200

            restore_resp = client.post("/api/v1/projects/demo/versions/scenes/庙宇/restore/1")
            assert restore_resp.status_code == 200
            assert restore_resp.json()["file_path"] == "scenes/庙宇.png"
            assert any(item[0] == "scene" for item in fake_pm.updated)

    def test_get_and_restore_props(self, monkeypatch):
        client, fake_pm = _client(monkeypatch)
        with client:
            get_resp = client.get("/api/v1/projects/demo/versions/props/玉佩")
            assert get_resp.status_code == 200

            restore_resp = client.post("/api/v1/projects/demo/versions/props/玉佩/restore/1")
            assert restore_resp.status_code == 200
            assert restore_resp.json()["file_path"] == "props/玉佩.png"
            assert any(item[0] == "prop" for item in fake_pm.updated)

    def test_restore_error_mapping(self, monkeypatch):
        client, _ = _client(monkeypatch)
        with client:
            bad_type = client.get("/api/v1/projects/demo/versions/bad/Alice")
            assert bad_type.status_code == 400

            not_found = client.post("/api/v1/projects/demo/versions/characters/Alice/restore/404")
            assert not_found.status_code == 404

            bad_value = client.post("/api/v1/projects/demo/versions/characters/Alice/restore/400")
            assert bad_value.status_code == 400

            unsupported = client.post("/api/v1/projects/demo/versions/unknown/Alice/restore/1")
            assert unsupported.status_code == 400

            # grids/reference_videos 是 VersionManager 合法类型，但本路由不放行其还原
            # （无还原后元数据同步分支），行为保持为 400——不因路径形状收敛而被静默放开。
            for unrestorable in ("grids", "reference_videos"):
                resp = client.post(f"/api/v1/projects/demo/versions/{unrestorable}/x/restore/1")
                assert resp.status_code == 400

    def test_resolve_resource_path_rejects_traversal(self):
        """resource_id 拼出的绝对路径若逃出项目目录，必须 400（路径遍历防护）。

        正常路由的 path 参数不会含 `/`，故直接对 helper 断言这道收口防护。
        """
        project_path = Path(tempfile.gettempdir()) / "demo"

        with pytest.raises(HTTPException) as exc:
            versions._resolve_resource_path(
                "characters",
                "../../../../etc/passwd",
                project_path,
                lambda key, **kw: key,
            )
        assert exc.value.status_code == 400

    def test_resolve_resource_path_accepts_normal_id(self):
        project_path = Path(tempfile.gettempdir()) / "demo"

        current_file, relative = versions._resolve_resource_path(
            "characters",
            "Alice",
            project_path,
            lambda key, **kw: key,
        )
        assert relative == "characters/Alice.png"
        # helper 返回未 resolve 的 project_path/relative，故用同一入参 base 拼接断言。
        assert current_file == project_path / "characters" / "Alice.png"

    def test_storyboard_restore_syncs_scripts_with_error_tolerance(self, tmp_path, monkeypatch):
        project_path = tmp_path / "demo"
        scripts_dir = project_path / "scripts"
        scripts_dir.mkdir(parents=True)
        for name in ("a.json", "b.json", "c.json"):
            (scripts_dir / name).write_text("{}", encoding="utf-8")

        fake_pm = _StoryboardSyncPM(project_path)
        monkeypatch.setattr(versions, "get_project_manager", lambda: fake_pm)
        monkeypatch.setattr(versions, "get_version_manager", lambda project_name: _FakeVM())

        app = FastAPI()
        app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="default", sub="testuser", role="admin")
        app.include_router(versions.router, prefix="/api/v1")
        with TestClient(app) as client:
            resp = client.post("/api/v1/projects/demo/versions/storyboards/E1S01/restore/1")
            assert resp.status_code == 200
            assert resp.json()["file_path"] == "storyboards/scene_E1S01.png"

        assert sorted(fake_pm.update_calls) == ["a.json", "b.json", "c.json"]

    def test_restore_returns_asset_fingerprints(self, monkeypatch, tmp_path):
        """版本还原应返回受影响文件的 fingerprint"""
        fake_pm = _FakePM()
        fake_pm.get_project_path = lambda name: tmp_path

        (tmp_path / "storyboards").mkdir()
        (tmp_path / "storyboards" / "scene_E1S01.png").write_bytes(b"restored")

        monkeypatch.setattr(versions, "get_project_manager", lambda: fake_pm)
        monkeypatch.setattr(versions, "get_version_manager", lambda name: _FakeVM())

        app = FastAPI()
        app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="default", sub="testuser", role="admin")
        app.include_router(versions.router, prefix="/api/v1")
        with TestClient(app) as client:
            resp = client.post("/api/v1/projects/demo/versions/storyboards/E1S01/restore/1")
            assert resp.status_code == 200
            data = resp.json()
            assert "asset_fingerprints" in data
            assert "storyboards/scene_E1S01.png" in data["asset_fingerprints"]
            assert isinstance(data["asset_fingerprints"]["storyboards/scene_E1S01.png"], int)

    def test_get_versions_unexpected_error_maps_to_500(self, monkeypatch):
        fake_pm = _FakePM()
        monkeypatch.setattr(versions, "get_project_manager", lambda: fake_pm)
        monkeypatch.setattr(
            versions,
            "get_version_manager",
            lambda project_name: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        app = FastAPI()
        app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="default", sub="testuser", role="admin")
        app.include_router(versions.router, prefix="/api/v1")
        with TestClient(app) as client:
            resp = client.get("/api/v1/projects/demo/versions/characters/Alice")
            assert resp.status_code == 500
            assert "boom" in resp.json()["detail"]

    def test_design_usage_blocks_whole_design_delete(self, monkeypatch, tmp_path):
        project_path = tmp_path / "demo"
        current_file = project_path / "characters" / "Alice.png"
        current_file.parent.mkdir(parents=True)
        current_file.write_bytes(b"current")

        vm = VersionManager(project_path)
        vm.add_version("characters", "Alice", "v1", current_file)

        project = {
            "characters": {"Alice": {"description": "hero", "character_sheet": "characters/Alice.png"}},
            "scenes": {},
            "props": {},
            "episodes": [{"script_file": "episode_1.json"}],
        }
        scripts = {
            "episode_1.json": {
                "episode": 1,
                "segments": [
                    {"segment_id": "E1S01", "characters_in_segment": ["Alice"], "scenes": [], "props": []}
                ],
            }
        }
        fake_pm = _DesignDeletePM(project_path, project, scripts)
        monkeypatch.setattr(versions, "get_project_manager", lambda: fake_pm)
        monkeypatch.setattr(versions, "get_version_manager", lambda name: VersionManager(project_path))

        app = FastAPI()
        app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="default", sub="testuser", role="admin")
        app.include_router(versions.router, prefix="/api/v1")
        with TestClient(app) as client:
            usage_resp = client.get("/api/v1/projects/demo/versions/characters/Alice/usage")
            assert usage_resp.status_code == 200
            assert usage_resp.json()["in_use"] is True
            assert usage_resp.json()["usages"][0]["kind"] == "segment"

            delete_resp = client.delete("/api/v1/projects/demo/versions/characters/Alice")
            assert delete_resp.status_code == 409
            assert delete_resp.json()["detail"] == "已应用，无法删除"

        assert "Alice" in project["characters"]
        assert current_file.exists()
        assert VersionManager(project_path).get_versions("characters", "Alice")["versions"]

    def test_delete_whole_design_removes_entry_files_and_versions(self, monkeypatch, tmp_path):
        project_path = tmp_path / "demo"
        current_file = project_path / "characters" / "Alice.png"
        reference_file = project_path / "characters" / "refs" / "Alice.png"
        reference_file.parent.mkdir(parents=True)
        current_file.parent.mkdir(parents=True, exist_ok=True)
        current_file.write_bytes(b"v1")
        reference_file.write_bytes(b"ref")

        vm = VersionManager(project_path)
        vm.add_version("characters", "Alice", "v1", current_file)
        current_file.write_bytes(b"v2")
        vm.add_version("characters", "Alice", "v2", current_file)

        project = {
            "characters": {
                "Alice": {
                    "description": "hero",
                    "character_sheet": "characters/Alice.png",
                    "reference_image": "characters/refs/Alice.png",
                }
            },
            "scenes": {},
            "props": {},
            "episodes": [{"script_file": "episode_1.json"}],
        }
        scripts = {
            "episode_1.json": {
                "episode": 1,
                "segments": [
                    {"segment_id": "E1S01", "characters_in_segment": [], "scenes": [], "props": []}
                ],
            }
        }
        fake_pm = _DesignDeletePM(project_path, project, scripts)
        monkeypatch.setattr(versions, "get_project_manager", lambda: fake_pm)
        monkeypatch.setattr(versions, "get_version_manager", lambda name: VersionManager(project_path))

        app = FastAPI()
        app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="default", sub="testuser", role="admin")
        app.include_router(versions.router, prefix="/api/v1")
        with TestClient(app) as client:
            resp = client.delete("/api/v1/projects/demo/versions/characters/Alice")
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["deleted_versions"] == 2
            assert data["failed_files"] == []
            assert data["asset_fingerprints"]["characters/Alice.png"] == 0

        assert "Alice" not in project["characters"]
        assert not current_file.exists()
        assert not reference_file.exists()
        assert VersionManager(project_path).get_versions("characters", "Alice")["versions"] == []

    def test_delete_whole_design_removes_entry_when_file_delete_fails(self, monkeypatch, tmp_path):
        project_path = tmp_path / "demo"
        current_dir = project_path / "characters" / "Alice.png"
        current_dir.mkdir(parents=True)

        project = {
            "characters": {"Alice": {"description": "hero", "character_sheet": "characters/Alice.png"}},
            "scenes": {},
            "props": {},
            "episodes": [{"script_file": "episode_1.json"}],
        }
        scripts = {
            "episode_1.json": {
                "episode": 1,
                "segments": [
                    {"segment_id": "E1S01", "characters_in_segment": [], "scenes": [], "props": []}
                ],
            }
        }
        fake_pm = _DesignDeletePM(project_path, project, scripts)
        monkeypatch.setattr(versions, "get_project_manager", lambda: fake_pm)
        monkeypatch.setattr(versions, "get_version_manager", lambda name: VersionManager(project_path))

        app = FastAPI()
        app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="default", sub="testuser", role="admin")
        app.include_router(versions.router, prefix="/api/v1")
        with TestClient(app) as client:
            resp = client.delete("/api/v1/projects/demo/versions/characters/Alice")
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["failed_files"] == ["characters/Alice.png"]
            assert "资源路径不是文件" in data["file_delete_errors"][0]["message"]

        assert "Alice" not in project["characters"]
        assert current_dir.is_dir()

    def test_delete_version_blocks_current_and_removes_non_current(self, monkeypatch, tmp_path):
        project_path = tmp_path / "demo"
        current_file = project_path / "characters" / "Alice.png"
        current_file.parent.mkdir(parents=True)
        current_file.write_bytes(b"v1")

        vm = VersionManager(project_path)
        vm.add_version("characters", "Alice", "v1", current_file)
        current_file.write_bytes(b"v2")
        vm.add_version("characters", "Alice", "v2", current_file)
        v1_file = project_path / vm.get_versions("characters", "Alice")["versions"][0]["file"]

        monkeypatch.setattr(versions, "get_version_manager", lambda name: VersionManager(project_path))

        app = FastAPI()
        app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="default", sub="testuser", role="admin")
        app.include_router(versions.router, prefix="/api/v1")
        with TestClient(app) as client:
            current_resp = client.delete("/api/v1/projects/demo/versions/characters/Alice/2")
            assert current_resp.status_code == 400
            assert "当前版本" in current_resp.json()["detail"]

            old_resp = client.delete("/api/v1/projects/demo/versions/characters/Alice/1")
            assert old_resp.status_code == 200
            assert old_resp.json()["deleted_version"] == 1
            assert old_resp.json()["failed_files"] == []

        remaining = VersionManager(project_path).get_versions("characters", "Alice")
        assert [item["version"] for item in remaining["versions"]] == [2]
        assert not v1_file.exists()

    def test_delete_version_removes_record_when_file_delete_fails(self, monkeypatch, tmp_path):
        project_path = tmp_path / "demo"
        current_file = project_path / "characters" / "Alice.png"
        current_file.parent.mkdir(parents=True)
        current_file.write_bytes(b"v1")

        vm = VersionManager(project_path)
        vm.add_version("characters", "Alice", "v1", current_file)
        current_file.write_bytes(b"v2")
        vm.add_version("characters", "Alice", "v2", current_file)
        v1_rel = vm.get_versions("characters", "Alice")["versions"][0]["file"]
        v1_file = project_path / v1_rel
        v1_file.unlink()
        v1_file.mkdir()

        monkeypatch.setattr(versions, "get_version_manager", lambda name: VersionManager(project_path))

        app = FastAPI()
        app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="default", sub="testuser", role="admin")
        app.include_router(versions.router, prefix="/api/v1")
        with TestClient(app) as client:
            resp = client.delete("/api/v1/projects/demo/versions/characters/Alice/1")
            assert resp.status_code == 200
            data = resp.json()
            assert data["deleted_version"] == 1
            assert data["failed_files"] == [v1_rel]
            assert "版本文件路径不是文件" in data["file_delete_errors"][0]["message"]

        remaining = VersionManager(project_path).get_versions("characters", "Alice")
        assert [item["version"] for item in remaining["versions"]] == [2]
        assert v1_file.is_dir()

    @pytest.mark.asyncio
    async def test_external_video_upload_copies_desktop_path_without_reading_stream(self, monkeypatch, tmp_path):
        project_path = tmp_path / "demo"
        source = tmp_path / "external.mp4"
        source.write_bytes(b"video-data")
        fake_pm = _ExternalUploadPM(project_path)
        fake_pm.project["characters"] = {"Alice": {"voice_style": "warm, calm voice"}}
        fake_pm.script["segments"][0]["characters_in_segment"] = ["Alice"]
        fake_pm.script["segments"][0]["video_prompt"] = {
            "action": "Alice 回头说话",
            "camera_motion": "Static",
            "dialogue": [{"speaker": "Alice", "line": "快走", "emotion": "urgent"}],
        }

        monkeypatch.setattr(versions, "get_project_manager", lambda: fake_pm)
        monkeypatch.setattr(versions, "get_version_manager", lambda name: VersionManager(project_path))

        async def _fake_thumbnail(current_file, thumbnail_file):
            return None

        monkeypatch.setattr(versions, "extract_video_thumbnail", _fake_thumbnail)
        monkeypatch.setattr(versions, "emit_project_change_batch", lambda *args, **kwargs: None)

        async def _fake_video_prompt_policy(project, payload=None, *, project_name=None):
            return VideoPromptPolicy(supports_generated_audio=False)

        monkeypatch.setattr(versions, "resolve_video_prompt_policy", _fake_video_prompt_policy)

        upload = SimpleNamespace(
            filename="external.mp4",
            path=source,
            file=_UnreadableUploadStream(),
        )

        result = await versions.upload_external_media_version(
            project_name="demo",
            resource_type="videos",
            resource_id="E1S01",
            _user=None,
            _t=lambda key, **kwargs: key,
            script_file="episode_1.json",
            file=upload,
        )

        current_path = project_path / result["file_path"]
        assert result["success"] is True
        assert current_path.read_bytes() == b"video-data"
        assert ("E1S01", "video_clip", result["file_path"]) in fake_pm.update_calls
        stored_prompt = VersionManager(project_path).get_versions("videos", "E1S01")["versions"][-1]["prompt"]
        assert "Voice_Style" not in stored_prompt
        assert "Mouth_Cue" not in stored_prompt
        assert "Speaking_Rules" not in stored_prompt
