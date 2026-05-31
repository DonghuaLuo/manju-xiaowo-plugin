from utils import arcreel_ipc_bridge, common


def _set_fake_windows_home(monkeypatch, home):
    monkeypatch.setattr(
        arcreel_ipc_bridge.Path,
        "home",
        classmethod(lambda cls: home),
    )


def test_detect_jianying_draft_root_prefers_custom_global_setting(tmp_path, monkeypatch):
    local_app_data = tmp_path / "LocalAppData"
    configured_draft_root = tmp_path / "D" / "program files" / "JianyingPro Drafts"
    default_draft_root = local_app_data / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft"
    configured_draft_root.mkdir(parents=True)
    default_draft_root.mkdir(parents=True)

    global_setting = local_app_data / "JianyingPro" / "User Data" / "Config" / "globalSetting"
    global_setting.parent.mkdir(parents=True)
    escaped_path = str(configured_draft_root).replace("\\", "\\\\")
    global_setting.write_text(
        f"[General]\ncurrentCustomDraftPath={escaped_path}\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(arcreel_ipc_bridge.platform, "system", lambda: "Windows")
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    _set_fake_windows_home(monkeypatch, tmp_path / "Home")

    assert arcreel_ipc_bridge._detect_jianying_draft_root() == str(configured_draft_root)


def test_detect_jianying_draft_root_falls_back_to_default_when_custom_missing(tmp_path, monkeypatch):
    local_app_data = tmp_path / "LocalAppData"
    missing_custom_root = tmp_path / "missing-custom"
    default_draft_root = local_app_data / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft"
    default_draft_root.mkdir(parents=True)

    global_setting = local_app_data / "JianyingPro" / "User Data" / "Config" / "globalSetting"
    global_setting.parent.mkdir(parents=True)
    global_setting.write_text(
        f"[General]\ncurrentCustomDraftPath={missing_custom_root}\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(arcreel_ipc_bridge.platform, "system", lambda: "Windows")
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    _set_fake_windows_home(monkeypatch, tmp_path / "Home")

    assert arcreel_ipc_bridge._detect_jianying_draft_root() == str(default_draft_root)


def test_open_desktop_path_reveals_file_in_explorer(tmp_path, monkeypatch):
    target_file = tmp_path / "demo-current.zip"
    target_file.write_text("zip", encoding="utf-8")
    opened: list[list[str]] = []

    monkeypatch.setattr(
        common.sys,
        "platform",
        "win32",
        raising=False,
    )
    monkeypatch.setattr(common.subprocess, "Popen", lambda args, **kwargs: opened.append(args))

    result = arcreel_ipc_bridge._open_desktop_path(str(target_file))

    assert result == {
        "path": str(target_file),
        "openedPath": str(tmp_path),
    }
    assert opened == [["explorer", "/select,", str(target_file.resolve())]]


def test_open_desktop_path_opens_directory_directly(tmp_path, monkeypatch):
    opened: list[list[str]] = []

    monkeypatch.setattr(
        common.sys,
        "platform",
        "win32",
        raising=False,
    )
    monkeypatch.setattr(common.subprocess, "Popen", lambda args, **kwargs: opened.append(args))

    result = arcreel_ipc_bridge._open_desktop_path(str(tmp_path))

    assert result == {
        "path": str(tmp_path),
        "openedPath": str(tmp_path),
    }
    assert opened == [["explorer", str(tmp_path.resolve())]]


def test_open_desktop_path_rejects_missing_directory(tmp_path):
    missing_dir = tmp_path / "missing"

    try:
        arcreel_ipc_bridge._open_desktop_path(str(missing_dir))
    except FileNotFoundError as exc:
        assert str(missing_dir) in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError")


def test_resolve_media_path_supports_favorite_style_thumbnail(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCREEL_DATA_DIR", str(tmp_path))
    from lib.app_data_dir import _reset_for_tests

    _reset_for_tests()
    thumbnail = tmp_path / "_style_favorites" / "images" / "favorite_demo.png"
    thumbnail.parent.mkdir(parents=True)
    thumbnail.write_bytes(b"png")

    result = arcreel_ipc_bridge.resolve_media_path({
        "resource": "style-templates/favorites/favorite_demo.png",
    })

    assert result == {"ok": True, "path": str(thumbnail)}
