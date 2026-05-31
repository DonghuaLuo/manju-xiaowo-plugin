"""Helpers for desktop/local UploadFile handling."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


def local_upload_path(file: Any) -> Path | None:
    """Return the original desktop path when the upload came from Xiaowo local-file IPC."""
    raw_path = getattr(file, "path", None)
    if not raw_path:
        return None
    path = Path(str(raw_path)).expanduser()
    return path if path.is_file() else None


def read_upload_bytes(file: Any, size: int = -1) -> bytes:
    """Read upload bytes from the local path when available, otherwise from the upload stream."""
    path = local_upload_path(file)
    if path is not None:
        with path.open("rb") as handle:
            return handle.read(size)

    handle = getattr(file, "file", None)
    if handle is None:
        return b""
    try:
        handle.seek(0)
    except Exception:
        pass
    return handle.read(size)


def copy_upload_file(file: Any, target: Path) -> None:
    """Copy an uploaded file to target without loading the whole file into memory."""
    target.parent.mkdir(parents=True, exist_ok=True)
    source = local_upload_path(file)
    if source is not None:
        try:
            if source.resolve() == target.resolve():
                return
        except OSError:
            pass
        shutil.copyfile(source, target)
        return

    handle = getattr(file, "file", None)
    if handle is None:
        raise FileNotFoundError("Uploaded file stream is not available")
    try:
        handle.seek(0)
    except Exception:
        pass
    with target.open("wb") as out:
        shutil.copyfileobj(handle, out)
