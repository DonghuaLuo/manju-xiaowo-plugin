#!/usr/bin/env python
"""Manage Manju backend-contained agent script registry records."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REQUIRED_FIELDS = {
    "script_id",
    "version",
    "status",
    "owner",
    "created_at",
    "updated_at",
    "summary",
    "working_directory",
    "entrypoints",
    "source_files",
    "evidence",
    "validation_commands",
    "tests",
    "failure_examples",
    "known_failures",
    "rollback",
    "notes",
}
OPTIONAL_FIELDS = {
    "repair_write_allowlist",
}
ALLOWED_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS

LIST_FIELDS = {
    "entrypoints",
    "source_files",
    "evidence",
    "validation_commands",
    "tests",
    "failure_examples",
    "known_failures",
    "rollback",
    "notes",
}

PATH_LIST_FIELDS = {"entrypoints", "source_files", "evidence", "tests", "failure_examples"}
VALID_STATUSES = {"default", "experimental", "deprecated"}
DEFAULT_REPAIR_WRITE_ALLOWLIST = ("agent_ops",)
REPAIR_SNAPSHOT_SKIP_DIRS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    ".codex",
    ".worktrees",
    ".superpowers",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "compile",
    "htmlcov",
    "projects",
    "logs",
}
REPAIR_SNAPSHOT_SKIP_PREFIXES = (
    "agent_ops/repair-runs/",
    "backend/agent_ops/repair-runs/",
)

FAILURE_REQUIRED_FIELDS = {
    "failure_id",
    "script_id",
    "category",
    "status",
    "observed_at",
    "summary",
    "input",
    "observed_output",
    "expected_behavior",
    "evidence",
    "regression_tests",
    "notes",
}
FAILURE_LIST_FIELDS = {"evidence", "regression_tests", "notes"}
FAILURE_PATH_LIST_FIELDS = {"evidence", "regression_tests"}
VALID_FAILURE_CATEGORIES = {
    "script_error",
    "upstream_api_error",
    "parse_error",
    "environment_error",
    "data_error",
}
VALID_FAILURE_STATUSES = {"open", "documented", "fixed", "regression_tested"}

SCRIPT_ID_RE = re.compile(r"^[a-z0-9_]+$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PYTHON_TOKENS = ("{python}", "{python_executable}")
LOCAL_ABSOLUTE_PATH_RE = re.compile(r"(^|[\s\"'`])([a-zA-Z]:[\\/]|\\\\)")
DEFAULT_REPAIR_OUTPUT_LIMIT = 20000


@dataclass(frozen=True)
class RegistryRecord:
    path: Path
    data: dict[str, Any]

    @property
    def script_id(self) -> str:
        return str(self.data.get("script_id", ""))

    @property
    def version(self) -> str:
        return str(self.data.get("version", ""))

    @property
    def status(self) -> str:
        return str(self.data.get("status", ""))


@dataclass(frozen=True)
class FailureExample:
    path: Path
    data: dict[str, Any]

    @property
    def failure_id(self) -> str:
        return str(self.data.get("failure_id", ""))

    @property
    def script_id(self) -> str:
        return str(self.data.get("script_id", ""))

    @property
    def status(self) -> str:
        return str(self.data.get("status", ""))


@dataclass(frozen=True)
class CommandFailure:
    record: RegistryRecord
    cwd: Path
    original_command: str
    expanded_command: str
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class RepairScopeViolation:
    changed_paths: list[str]
    allowed_paths: list[str]


@dataclass(frozen=True)
class RepairFileSnapshot:
    hashes: dict[str, str]
    paths: dict[str, Path]
    backups: dict[str, Path]
    backup_dir: Path | None = None


def backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def plugin_root() -> Path:
    """Backward-compatible alias for the backend execution root."""
    return backend_root()


def registry_dir(root: Path | None = None) -> Path:
    return (root or backend_root()) / "agent_ops" / "registry"


def failure_examples_dir(root: Path | None = None) -> Path:
    return registry_dir(root) / "failure-examples"


def stable_snapshots_dir(root: Path | None = None) -> Path:
    return registry_dir(root) / "stable"


def repair_runs_dir(root: Path | None = None) -> Path:
    return (root or backend_root()) / "agent_ops" / "repair-runs"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _relative_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def load_registry(root: Path | None = None) -> list[RegistryRecord]:
    root = root or backend_root()
    directory = registry_dir(root)
    records: list[RegistryRecord] = []
    for path in sorted(directory.glob("*.json")):
        if path.name == "schema.json":
            continue
        records.append(RegistryRecord(path=path, data=_read_json(path)))
    return records


def load_failure_examples(root: Path | None = None) -> list[FailureExample]:
    root = root or backend_root()
    directory = failure_examples_dir(root)
    if not directory.exists():
        return []
    return [FailureExample(path=path, data=_read_json(path)) for path in sorted(directory.glob("*.json"))]


def _path_without_symbol(value: str) -> str:
    stripped = value.strip()
    if re.match(r"^[a-zA-Z]:[\\/]", stripped):
        return stripped
    return stripped.split(":", 1)[0]


def _is_manual(value: str) -> bool:
    return value.strip().startswith("manual:")


def _is_external_ref(value: str) -> bool:
    return bool(re.match(r"^[a-zA-Z]+://", value.strip()))


def _current_python_command() -> str:
    return subprocess.list2cmdline([sys.executable])


def _expand_runtime_tokens(command: str) -> str:
    expanded = command
    for token in PYTHON_TOKENS:
        expanded = expanded.replace(token, _current_python_command())
    return expanded


def _shell_arg(value: str | Path) -> str:
    return subprocess.list2cmdline([str(value)])


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _truncate_output(value: str, limit: int = DEFAULT_REPAIR_OUTPUT_LIMIT) -> str:
    if len(value) <= limit:
        return value
    return value[-limit:]


def _validate_existing_path(root: Path, label: str, field: str, value: str) -> list[str]:
    if _is_manual(value):
        return []
    raw_path = _path_without_symbol(value)
    if not raw_path or _is_external_ref(raw_path):
        return []
    path = (root / raw_path).resolve()
    if not _is_within_root(root, path):
        return [f"{label}: {field} path must stay within backend root: {value}"]
    if not path.exists():
        return [f"{label}: {field} path does not exist: {value}"]
    return []


def _validate_no_local_absolute_path(label: str, field: str, value: str) -> list[str]:
    if LOCAL_ABSOLUTE_PATH_RE.search(value):
        return [f"{label}: {field} must not contain a local absolute path: {value}"]
    return []


def _is_within_root(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _validate_string_list(label: str, field: str, value: Any) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item.strip() for item in value):
        return [f"{label}: {field} must be a non-empty list of strings"]
    return []


def _semver_key(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return (-1, -1, -1)
    return tuple(int(part) for part in parts)  # type: ignore[return-value]


def _resolve_working_directory(root: Path, record: RegistryRecord) -> Path:
    raw = str(record.data.get("working_directory", ".")).strip()
    return (root / raw).resolve()


def _validate_record(root: Path, record: RegistryRecord) -> list[str]:
    errors: list[str] = []
    data = record.data
    label = record.path.name

    missing = sorted(REQUIRED_FIELDS - data.keys())
    if missing:
        errors.append(f"{label}: missing required fields: {', '.join(missing)}")
    extra = sorted(data.keys() - ALLOWED_FIELDS)
    if extra:
        errors.append(f"{label}: unknown fields: {', '.join(extra)}")

    script_id = str(data.get("script_id", ""))
    if not SCRIPT_ID_RE.match(script_id):
        errors.append(f"{label}: invalid script_id: {script_id}")
    if record.path.stem != script_id:
        errors.append(f"{label}: filename must match script_id")

    version = str(data.get("version", ""))
    if not SEMVER_RE.match(version):
        errors.append(f"{label}: invalid semver version: {version}")

    status = str(data.get("status", ""))
    if status not in VALID_STATUSES:
        errors.append(f"{label}: invalid status: {status}")

    for field in ("created_at", "updated_at"):
        value = str(data.get(field, ""))
        if not DATE_RE.match(value):
            errors.append(f"{label}: invalid {field}: {value}")

    working_directory = data.get("working_directory")
    if not isinstance(working_directory, str) or not working_directory.strip():
        errors.append(f"{label}: working_directory must be a non-empty string")
    else:
        errors.extend(_validate_no_local_absolute_path(label, "working_directory", working_directory))
        path = _resolve_working_directory(root, record)
        if not _is_within_root(root, path):
            errors.append(f"{label}: working_directory must stay within backend root: {working_directory}")
        elif not path.exists() or not path.is_dir():
            errors.append(f"{label}: working_directory does not exist: {working_directory}")

    for field in LIST_FIELDS:
        value = data.get(field)
        list_errors = _validate_string_list(label, field, value)
        errors.extend(list_errors)
        if list_errors or field not in PATH_LIST_FIELDS:
            if not list_errors and isinstance(value, list):
                for item in value:
                    errors.extend(_validate_no_local_absolute_path(label, field, item))
            continue
        for item in value:
            errors.extend(_validate_no_local_absolute_path(label, field, item))
            errors.extend(_validate_existing_path(root, label, field, item))

    repair_allowlist = data.get("repair_write_allowlist")
    if repair_allowlist is not None:
        list_errors = _validate_string_list(label, "repair_write_allowlist", repair_allowlist)
        errors.extend(list_errors)
        if not list_errors:
            for item in repair_allowlist:
                errors.extend(_validate_no_local_absolute_path(label, "repair_write_allowlist", item))
                errors.extend(_validate_existing_path(root, label, "repair_write_allowlist", item))

    return errors


def _validate_failure_example(
    root: Path,
    example: FailureExample,
    records_by_id: dict[str, RegistryRecord],
) -> list[str]:
    errors: list[str] = []
    data = example.data
    label = example.path.name

    missing = sorted(FAILURE_REQUIRED_FIELDS - data.keys())
    if missing:
        errors.append(f"{label}: missing required fields: {', '.join(missing)}")
    extra = sorted(data.keys() - FAILURE_REQUIRED_FIELDS)
    if extra:
        errors.append(f"{label}: unknown fields: {', '.join(extra)}")

    failure_id = str(data.get("failure_id", ""))
    if not SCRIPT_ID_RE.match(failure_id):
        errors.append(f"{label}: invalid failure_id: {failure_id}")
    if example.path.stem != failure_id:
        errors.append(f"{label}: filename must match failure_id")

    script_id = str(data.get("script_id", ""))
    if script_id not in records_by_id:
        errors.append(f"{label}: unknown script_id: {script_id}")

    category = str(data.get("category", ""))
    if category not in VALID_FAILURE_CATEGORIES:
        errors.append(f"{label}: invalid category: {category}")

    status = str(data.get("status", ""))
    if status not in VALID_FAILURE_STATUSES:
        errors.append(f"{label}: invalid status: {status}")

    observed_at = str(data.get("observed_at", ""))
    if not DATE_RE.match(observed_at):
        errors.append(f"{label}: invalid observed_at: {observed_at}")

    for field in ("summary", "expected_behavior"):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{label}: {field} must be a non-empty string")

    for field in FAILURE_LIST_FIELDS:
        value = data.get(field)
        list_errors = _validate_string_list(label, field, value)
        errors.extend(list_errors)
        if list_errors or field not in FAILURE_PATH_LIST_FIELDS:
            continue
        for item in value:
            errors.extend(_validate_existing_path(root, label, field, item))

    return errors


def _validate_failure_example_links(
    root: Path,
    records: list[RegistryRecord],
    examples: list[FailureExample],
) -> list[str]:
    errors: list[str] = []
    examples_by_path = {_relative_path(root, example.path): example for example in examples}
    for record in records:
        for item in record.data.get("failure_examples", []):
            example = examples_by_path.get(item)
            if example is None:
                continue
            if example.script_id != record.script_id:
                errors.append(
                    f"{record.path.name}: failure example {item} belongs to {example.script_id}, "
                    f"not {record.script_id}"
                )
    return errors


def _validate_stable_snapshots(root: Path, records: list[RegistryRecord]) -> list[str]:
    errors: list[str] = []
    directory = stable_snapshots_dir(root)
    default_records = [record for record in records if record.status == "default"]
    if default_records and not directory.exists():
        return [f"stable snapshot directory does not exist: {directory}"]

    for record in default_records:
        path = directory / f"{record.script_id}-{record.version}.json"
        if not path.exists():
            errors.append(f"{record.path.name}: stable snapshot does not exist: {_relative_path(root, path)}")
            continue
        data = _read_json(path)
        if data.get("script_id") != record.script_id:
            errors.append(f"{path.name}: stable snapshot script_id mismatch")
        if data.get("version") != record.version:
            errors.append(f"{path.name}: stable snapshot version mismatch")
        if data.get("status") != "default":
            errors.append(f"{path.name}: stable snapshot must keep status=default")
        if data != record.data:
            errors.append(
                f"{record.path.name}: stable snapshot differs from current default record: "
                f"{_relative_path(root, path)}"
            )
    return errors


def validate_registry(root: Path | None = None, require_current_snapshots: bool = True) -> list[str]:
    root = root or backend_root()
    directory = registry_dir(root)
    errors: list[str] = []
    if not directory.exists():
        return [f"registry directory does not exist: {directory}"]

    records = load_registry(root)
    if not records:
        return [f"registry has no records: {directory}"]

    seen: set[str] = set()
    for record in records:
        errors.extend(_validate_record(root, record))
        if record.script_id in seen:
            errors.append(f"{record.path.name}: duplicate script_id: {record.script_id}")
        seen.add(record.script_id)

    records_by_id = {record.script_id: record for record in records}
    examples = load_failure_examples(root)
    if not examples:
        errors.append(f"failure example library has no records: {failure_examples_dir(root)}")
    for example in examples:
        errors.extend(_validate_failure_example(root, example, records_by_id))
    errors.extend(_validate_failure_example_links(root, records, examples))
    if require_current_snapshots:
        errors.extend(_validate_stable_snapshots(root, records))

    return errors


def _select_records(root: Path, script_id: str | None, all_defaults: bool) -> tuple[list[RegistryRecord], list[str]]:
    records = load_registry(root)
    errors: list[str] = []
    if all_defaults:
        selected = [record for record in records if record.status == "default"]
        if not selected:
            errors.append("no default records found")
        return selected, errors

    if not script_id:
        errors.append("script_id is required unless --all-defaults is used")
        return [], errors

    selected = [record for record in records if record.script_id == script_id and record.status == "default"]
    if not selected:
        errors.append(f"default record not found for script_id: {script_id}")
    return selected, errors


def _stable_snapshot_records(root: Path, script_id: str) -> list[RegistryRecord]:
    directory = stable_snapshots_dir(root)
    if not directory.exists():
        return []
    snapshots: list[RegistryRecord] = []
    for path in directory.glob(f"{script_id}-*.json"):
        data = _read_json(path)
        if data.get("script_id") == script_id:
            snapshots.append(RegistryRecord(path=path, data=data))
    return sorted(snapshots, key=lambda record: _semver_key(record.version), reverse=True)


def write_stable_snapshot(root: Path, record: RegistryRecord, force: bool = False) -> str:
    directory = stable_snapshots_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{record.script_id}-{record.version}.json"
    payload = _dump_json(record.data)
    if path.exists():
        if _read_json(path) == record.data:
            return f"SKIP: stable snapshot already current: {_relative_path(root, path)}"
        if not force:
            return f"SKIP: stable snapshot exists, use --force to overwrite: {_relative_path(root, path)}"
    path.write_text(payload, encoding="utf-8")
    return f"OK: wrote stable snapshot: {_relative_path(root, path)}"


def rollback_record(root: Path, script_id: str, dry_run: bool = False) -> tuple[int, str]:
    snapshots = _stable_snapshot_records(root, script_id)
    if not snapshots:
        return 1, f"ERROR: no stable snapshot found for script_id: {script_id}"

    snapshot = snapshots[0]
    target = registry_dir(root) / f"{script_id}.json"
    message = f"rollback {script_id} to stable {snapshot.version} from {_relative_path(root, snapshot.path)}"
    if dry_run:
        return 0, f"DRY-RUN: {message}"
    target.write_text(_dump_json(snapshot.data), encoding="utf-8")
    return 0, f"OK: {message}"


def write_repair_task(
    root: Path,
    failure: CommandFailure,
    repair_dir: Path | None = None,
) -> Path:
    directory = repair_dir or repair_runs_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    snapshots = _stable_snapshot_records(root, failure.record.script_id)
    latest_stable = _relative_path(root, snapshots[0].path) if snapshots else None
    repair_write_allowlist = _repair_write_allowlist(failure.record)
    payload = {
        "schema_version": 1,
        "repair_agent_type": "ops_agent",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "script_id": failure.record.script_id,
        "version": failure.record.version,
        "status": failure.record.status,
        "registry_record_path": _relative_path(root, failure.record.path),
        "working_directory": str(failure.record.data.get("working_directory", ".")),
        "resolved_working_directory": _relative_path(root, failure.cwd),
        "failed_command": failure.original_command,
        "expanded_command_for_this_run": failure.expanded_command,
        "exit_code": failure.returncode,
        "stdout_tail": _truncate_output(failure.stdout),
        "stderr_tail": _truncate_output(failure.stderr),
        "latest_stable_snapshot": latest_stable,
        "entrypoints": failure.record.data.get("entrypoints", []),
        "source_files": failure.record.data.get("source_files", []),
        "evidence": failure.record.data.get("evidence", []),
        "tests": failure.record.data.get("tests", []),
        "failure_examples": failure.record.data.get("failure_examples", []),
        "known_failures": failure.record.data.get("known_failures", []),
        "repair_write_allowlist": repair_write_allowlist,
        "required_agent_actions": [
            "复现 failed_command 对应的失败。",
            "读取 entrypoints、source_files、evidence、failure_examples 定位原因。",
            "只修改 repair_write_allowlist 中声明的路径范围。",
            "修改脚本、调用链或 registry 记录，并补充或更新回归测试。",
            "重新运行 validation_commands 中的自动命令。",
            "验证通过后更新版本记录；需要沉淀稳定版本时运行 snapshot。",
        ],
        "success_contract": [
            "失败样例被覆盖。",
            "原有成功路径不回归。",
            "validation_commands 全部自动命令通过。",
            "git diff --check 通过。",
        ],
        "validation_commands": failure.record.data.get("validation_commands", []),
    }
    path = directory / f"{failure.record.script_id}-{failure.record.version}-{_utc_stamp()}.json"
    path.write_text(_dump_json(payload), encoding="utf-8")
    return path


def _repair_write_allowlist(record: RegistryRecord) -> list[str]:
    raw = record.data.get("repair_write_allowlist")
    if isinstance(raw, list) and raw:
        return [str(item).strip().replace(chr(92), "/").rstrip("/") for item in raw if str(item).strip()]
    return list(DEFAULT_REPAIR_WRITE_ALLOWLIST)


def _repair_allowed_roots(root: Path, record: RegistryRecord) -> list[Path]:
    allowed: list[Path] = []
    for item in _repair_write_allowlist(record):
        if _is_manual(item) or _is_external_ref(item):
            continue
        raw_path = _path_without_symbol(item).replace(chr(92), "/").rstrip("/")
        if not raw_path:
            continue
        path = (root / raw_path).resolve()
        if _is_within_root(root, path):
            allowed.append(path)
    return allowed


def _repair_path_is_allowed(path: Path, allowed_roots: list[Path]) -> bool:
    resolved = path.resolve(strict=False)
    return any(resolved == allowed or resolved.is_relative_to(allowed) for allowed in allowed_roots)


def _repair_scan_root(root: Path) -> Path:
    git_root_result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if git_root_result.returncode == 0 and git_root_result.stdout.strip():
        git_root = Path(git_root_result.stdout.strip()).resolve()
        if root.resolve().is_relative_to(git_root):
            return git_root
    return root.resolve()


def _repair_snapshot_key(root: Path, path: Path) -> str:
    return Path(os.path.relpath(path.resolve(strict=False), root.resolve())).as_posix()


def _should_skip_snapshot_path(scan_root: Path, root: Path, path: Path) -> bool:
    try:
        rel_parts = path.resolve(strict=False).relative_to(scan_root.resolve()).parts
    except ValueError:
        return True
    if any(part in REPAIR_SNAPSHOT_SKIP_DIRS for part in rel_parts):
        return True
    rel = "/".join(rel_parts)
    if any(rel.startswith(prefix) for prefix in REPAIR_SNAPSHOT_SKIP_PREFIXES):
        return True
    root_rel = _repair_snapshot_key(root, path)
    return any(root_rel.startswith(prefix) for prefix in REPAIR_SNAPSHOT_SKIP_PREFIXES)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backup_rel_path(rel: str) -> Path:
    parts = [
        "__parent__" if part == ".." else part.replace(":", "_drive")
        for part in rel.split("/")
        if part
    ]
    return Path(*parts)


def _iter_repair_snapshot_files(root: Path) -> list[Path]:
    scan_root = _repair_scan_root(root)
    paths: list[Path] = []
    for current, dirnames, filenames in os.walk(scan_root):
        current_path = Path(current)
        kept_dirs: list[str] = []
        for dirname in dirnames:
            child = current_path / dirname
            if _should_skip_snapshot_path(scan_root, root, child):
                continue
            kept_dirs.append(dirname)
        dirnames[:] = kept_dirs
        for filename in filenames:
            path = current_path / filename
            if path.is_file() and not _should_skip_snapshot_path(scan_root, root, path):
                paths.append(path)
    return paths


def _repair_file_snapshot(root: Path, *, keep_backups: bool = False) -> RepairFileSnapshot:
    snapshot: dict[str, str] = {}
    path_by_key: dict[str, Path] = {}
    backup_by_key: dict[str, Path] = {}
    backup_dir = Path(tempfile.mkdtemp(prefix="manju-agent-ops-repair-")) if keep_backups else None
    for path in _iter_repair_snapshot_files(root):
        try:
            rel = _repair_snapshot_key(root, path)
            snapshot[rel] = _hash_file(path)
            path_by_key[rel] = path
            if backup_dir is not None:
                backup_path = backup_dir / _backup_rel_path(rel)
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, backup_path)
                backup_by_key[rel] = backup_path
        except OSError:
            continue
    return RepairFileSnapshot(
        hashes=snapshot,
        paths=path_by_key,
        backups=backup_by_key,
        backup_dir=backup_dir,
    )


def _repair_changed_paths(before: RepairFileSnapshot, after: RepairFileSnapshot) -> list[str]:
    keys = set(before.hashes) | set(after.hashes)
    return sorted(path for path in keys if before.hashes.get(path) != after.hashes.get(path))


def _check_repair_scope(
    root: Path,
    record: RegistryRecord,
    before: RepairFileSnapshot,
    after: RepairFileSnapshot,
) -> RepairScopeViolation | None:
    changed = _repair_changed_paths(before, after)
    if not changed:
        return None
    allowed_roots = _repair_allowed_roots(root, record)
    rejected = [path for path in changed if not _repair_path_is_allowed(root / path, allowed_roots)]
    if not rejected:
        return None
    return RepairScopeViolation(
        changed_paths=rejected,
        allowed_paths=_repair_write_allowlist(record),
    )


def _restore_repair_changes(root: Path, before: RepairFileSnapshot, after: RepairFileSnapshot) -> None:
    for rel in _repair_changed_paths(before, after):
        target = before.paths.get(rel) or after.paths.get(rel) or (root / rel).resolve(strict=False)
        backup = before.backups.get(rel)
        if backup is not None and backup.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
        elif target.exists() and target.is_file():
            target.unlink()


def _cleanup_repair_snapshot(snapshot: RepairFileSnapshot) -> None:
    if snapshot.backup_dir is not None and snapshot.backup_dir.exists():
        shutil.rmtree(snapshot.backup_dir, ignore_errors=True)


def _render_agent_command(template: str, repair_task: Path, failure: CommandFailure) -> str:
    expanded = template
    replacements = {
        "{repair_task}": _shell_arg(repair_task),
        "{script_id}": failure.record.script_id,
        "{version}": failure.record.version,
        "{failed_command}": _shell_arg(failure.original_command),
    }
    for token in PYTHON_TOKENS:
        replacements[token] = _current_python_command()
    for token, value in replacements.items():
        expanded = expanded.replace(token, value)
    return expanded


def _run_repair_agent(root: Path, agent_command: str, repair_task: Path, failure: CommandFailure) -> int:
    command = _render_agent_command(agent_command, repair_task, failure)
    print(f"REPAIR-AGENT: {command}", flush=True)
    completed = subprocess.run(command, cwd=root, shell=True)
    if completed.returncode != 0:
        print(f"ERROR: repair agent failed with exit code {completed.returncode}: {command}")
    return completed.returncode


def _run_record_once(
    root: Path,
    record: RegistryRecord,
    dry_run: bool,
    *,
    capture_failure: bool = False,
) -> tuple[int, CommandFailure | None]:
    cwd = _resolve_working_directory(root, record)
    commands = list(record.data.get("validation_commands", []))
    automatic_commands = [command for command in commands if not _is_manual(command)]
    manual_commands = [command for command in commands if _is_manual(command)]

    print(f"== {record.script_id} {record.version} ({record.status}) ==")
    print(f"cwd: {cwd}")
    for command in manual_commands:
        print(f"SKIP manual command: {command}")
    if not automatic_commands:
        print("OK: no automatic validation commands to run")
        return 0

    for command in automatic_commands:
        original_command = command
        command = _expand_runtime_tokens(command)
        if dry_run:
            print(f"DRY-RUN: {command}")
            continue
        print(f"RUN: {command}", flush=True)
        completed = subprocess.run(
            command,
            cwd=cwd,
            shell=True,
            capture_output=capture_failure,
            text=capture_failure,
            encoding="utf-8" if capture_failure else None,
            errors="replace" if capture_failure else None,
        )
        if capture_failure:
            if completed.stdout:
                print(completed.stdout, end="")
            if completed.stderr:
                print(completed.stderr, end="", file=sys.stderr)
        if completed.returncode != 0:
            print(f"ERROR: command failed with exit code {completed.returncode}: {command}")
            failure = CommandFailure(
                record=record,
                cwd=cwd,
                original_command=original_command,
                expanded_command=command,
                returncode=completed.returncode,
                stdout=completed.stdout or "",
                stderr=completed.stderr or "",
            )
            return completed.returncode, failure
    return 0, None


def _run_record(root: Path, record: RegistryRecord, dry_run: bool, rollback_on_failure: bool) -> int:
    code, failure = _run_record_once(root, record, dry_run)
    if failure and rollback_on_failure:
        rollback_code, rollback_message = rollback_record(root, record.script_id, dry_run=False)
        print(rollback_message)
        return code if rollback_code == 0 else rollback_code
    return code


def _run_record_with_repair(
    root: Path,
    record: RegistryRecord,
    dry_run: bool,
    *,
    agent_command: str | None,
    repair_dir: Path | None,
    rollback_on_failure: bool,
    max_repair_attempts: int,
) -> int:
    attempts = max(1, max_repair_attempts)
    current_record = record
    for attempt in range(1, attempts + 1):
        code, failure = _run_record_once(root, current_record, dry_run, capture_failure=not dry_run)
        if code == 0 or failure is None or dry_run:
            return code

        repair_task = write_repair_task(root, failure, repair_dir=repair_dir)
        print(f"REPAIR-TASK: {_relative_path(root, repair_task)}")
        command = agent_command or os.environ.get("MANJU_AGENT_OPS_AGENT_COMMAND")
        if not command:
            print(
                "ERROR: validation failed and repair task was written, "
                "but no repair agent command was provided. Use --agent-command or MANJU_AGENT_OPS_AGENT_COMMAND."
            )
            if rollback_on_failure:
                rollback_code, rollback_message = rollback_record(root, record.script_id, dry_run=False)
                print(rollback_message)
                return code if rollback_code == 0 else rollback_code
            return code

        before_repair = _repair_file_snapshot(root, keep_backups=True)
        try:
            agent_code = _run_repair_agent(root, command, repair_task, failure)
            after_repair = _repair_file_snapshot(root)
            scope_violation = _check_repair_scope(root, current_record, before_repair, after_repair)
            if scope_violation is not None:
                _restore_repair_changes(root, before_repair, after_repair)
                print("ERROR: repair ops agent modified paths outside repair_write_allowlist; changes restored:")
                for path in scope_violation.changed_paths:
                    print(f"  - {path}")
                print("Allowed repair write paths:")
                for path in scope_violation.allowed_paths:
                    print(f"  - {path}")
                return 1
        finally:
            _cleanup_repair_snapshot(before_repair)
        if agent_code != 0:
            if rollback_on_failure:
                rollback_code, rollback_message = rollback_record(root, record.script_id, dry_run=False)
                print(rollback_message)
                return agent_code if rollback_code == 0 else rollback_code
            return agent_code

        current_record = next(
            (
                candidate
                for candidate in load_registry(root)
                if candidate.script_id == record.script_id and candidate.status == "default"
            ),
            current_record,
        )
        if attempt < attempts:
            print(f"RETRY: validation after repair agent attempt {attempt}/{attempts}")
    code, failure = _run_record_once(root, current_record, dry_run, capture_failure=not dry_run)
    if code != 0 and failure and rollback_on_failure:
        rollback_code, rollback_message = rollback_record(root, record.script_id, dry_run=False)
        print(rollback_message)
        return code if rollback_code == 0 else rollback_code
    return code


def cmd_validate(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else backend_root()
    errors = validate_registry(root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"OK: {len(load_registry(root))} agent script records validated")
    print(f"OK: {len(load_failure_examples(root))} failure examples validated")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else backend_root()
    records = load_registry(root)
    for record in records:
        print(f"{record.script_id}\t{record.version}\t{record.status}")
    return 0


def cmd_failure_examples(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else backend_root()
    examples = load_failure_examples(root)
    for example in examples:
        print(f"{example.failure_id}\t{example.script_id}\t{example.status}")
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else backend_root()
    records, errors = _select_records(root, args.script_id, args.all_defaults)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    for record in records:
        print(write_stable_snapshot(root, record, force=args.force))
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else backend_root()
    code, message = rollback_record(root, args.script_id, dry_run=args.dry_run)
    print(message)
    return code


def cmd_run(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else backend_root()
    errors = validate_registry(root, require_current_snapshots=False)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    records, select_errors = _select_records(root, args.script_id, args.all_defaults)
    if select_errors:
        for error in select_errors:
            print(f"ERROR: {error}")
        return 1
    repair_dir = Path(args.repair_dir).resolve() if args.repair_dir else None
    for record in records:
        if args.repair_on_failure:
            code = _run_record_with_repair(
                root,
                record,
                dry_run=args.dry_run,
                agent_command=args.agent_command,
                repair_dir=repair_dir,
                rollback_on_failure=args.rollback_on_failure,
                max_repair_attempts=args.max_repair_attempts,
            )
        else:
            code = _run_record(root, record, dry_run=args.dry_run, rollback_on_failure=args.rollback_on_failure)
        if code != 0:
            return code
        if args.snapshot_on_success and not args.dry_run:
            current_record = next(
                (
                    candidate
                    for candidate in load_registry(root)
                    if candidate.script_id == record.script_id and candidate.status == "default"
                ),
                record,
            )
            print(write_stable_snapshot(root, current_record, force=args.force_snapshot))
    return 0


def cmd_repair(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else backend_root()
    records, errors = _select_records(root, args.script_id, all_defaults=False)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    record = records[0]
    code, failure = _run_record_once(root, record, dry_run=False, capture_failure=True)
    if code == 0 or failure is None:
        print(f"OK: {record.script_id} validation passed; no repair task needed")
        return 0
    repair_dir = Path(args.repair_dir).resolve() if args.repair_dir else None
    repair_task = write_repair_task(root, failure, repair_dir=repair_dir)
    print(f"REPAIR-TASK: {_relative_path(root, repair_task)}")
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="Backend root path. Defaults to the current Manju backend root.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate registry records.")
    validate_parser.set_defaults(func=cmd_validate)

    list_parser = subparsers.add_parser("list", help="List registry records.")
    list_parser.set_defaults(func=cmd_list)

    examples_parser = subparsers.add_parser("failure-examples", help="List failure example records.")
    examples_parser.set_defaults(func=cmd_failure_examples)

    snapshot_parser = subparsers.add_parser("snapshot", help="Save current default records as stable snapshots.")
    snapshot_parser.add_argument("script_id", nargs="?", help="Default script_id to snapshot.")
    snapshot_parser.add_argument("--all-defaults", action="store_true", help="Snapshot every default registry record.")
    snapshot_parser.add_argument("--force", action="store_true", help="Overwrite an existing stable snapshot.")
    snapshot_parser.set_defaults(func=cmd_snapshot)

    rollback_parser = subparsers.add_parser("rollback", help="Restore a registry record from its latest stable snapshot.")
    rollback_parser.add_argument("script_id", help="Script id to roll back.")
    rollback_parser.add_argument("--dry-run", action="store_true", help="Show the rollback target without writing files.")
    rollback_parser.set_defaults(func=cmd_rollback)

    run_parser = subparsers.add_parser("run", help="Run validation commands for default script records.")
    run_parser.add_argument("script_id", nargs="?", help="Default script_id to run.")
    run_parser.add_argument("--all-defaults", action="store_true", help="Run every default registry record.")
    run_parser.add_argument("--dry-run", action="store_true", help="Print commands without executing them.")
    run_parser.add_argument(
        "--snapshot-on-success",
        action="store_true",
        help="Write a stable snapshot for each record after its automatic validation commands pass.",
    )
    run_parser.add_argument(
        "--force-snapshot",
        action="store_true",
        help="Overwrite an existing stable snapshot when used with --snapshot-on-success.",
    )
    run_parser.add_argument(
        "--rollback-on-failure",
        action="store_true",
        help="Restore the record from the latest stable snapshot if validation fails.",
    )
    run_parser.add_argument(
        "--repair-on-failure",
        action="store_true",
        help="Write a repair task and launch a repair agent command when validation fails.",
    )
    run_parser.add_argument(
        "--agent-command",
        help=(
            "Repair agent command template. Supports {repair_task}, {python}, {python_executable}, "
            "{script_id}, {version}, and {failed_command}."
        ),
    )
    run_parser.add_argument("--repair-dir", help="Directory for generated repair tasks. Defaults to agent_ops/repair-runs.")
    run_parser.add_argument(
        "--max-repair-attempts",
        type=int,
        default=1,
        help="Maximum repair agent attempts before returning failure.",
    )
    run_parser.set_defaults(func=cmd_run)

    repair_parser = subparsers.add_parser("repair", help="Run one default record and write a repair task on failure.")
    repair_parser.add_argument("script_id", help="Default script_id to diagnose.")
    repair_parser.add_argument("--repair-dir", help="Directory for generated repair tasks. Defaults to agent_ops/repair-runs.")
    repair_parser.set_defaults(func=cmd_repair)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
