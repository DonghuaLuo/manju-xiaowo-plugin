from utils import arcreel_ipc_bridge, common


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
