from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from agent_script_registry import (  # noqa: E402
    backend_root,
    load_failure_examples,
    load_registry,
    main,
    repair_runs_dir,
    rollback_record,
    stable_snapshots_dir,
    validate_registry,
)

LOCAL_ABSOLUTE_PATH_RE = re.compile(r"(^|[\s\"'`])([a-zA-Z]:[\\/]|\\\\)")


def test_agent_script_registry_records_are_valid() -> None:
    errors = validate_registry(backend_root())

    assert errors == []


def test_agent_script_registry_covers_first_phase_scripts() -> None:
    records = {record.script_id: record for record in load_registry(backend_root())}
    default_ids = {record.script_id for record in records.values() if record.status == "default"}

    assert {
        "agent_script_registry_flow",
        "text_structured_output_probe",
        "plugin_release_pipeline",
        "custom_provider_model_discovery",
    }.issubset(records)
    assert {
        "agent_script_registry_flow",
        "text_structured_output_probe",
        "custom_provider_model_discovery",
    }.issubset(default_ids)
    assert records["plugin_release_pipeline"].status == "deprecated"


def test_text_structured_output_probe_registry_keeps_regression_tests() -> None:
    records = {record.script_id: record for record in load_registry(backend_root())}
    tests = set(records["text_structured_output_probe"].data["tests"])

    assert "agent_ops/tests/text_structured_output_probe_smoke.py" in tests
    assert "tests/test_text_structured_probe.py" in tests
    assert "tests/test_openai_text_backend.py" in tests


def test_agent_script_registry_tracks_failure_examples_and_stable_snapshots() -> None:
    root = backend_root()
    records = {record.script_id: record for record in load_registry(root)}
    examples = {example.failure_id: example for example in load_failure_examples(root)}

    assert "text_structured_output_probe_schema_not_enforced" in examples
    assert examples["text_structured_output_probe_schema_not_enforced"].script_id == "text_structured_output_probe"
    assert records["text_structured_output_probe"].data["failure_examples"] == [
        "agent_ops/registry/failure-examples/text_structured_output_probe_schema_not_enforced.json"
    ]
    assert (stable_snapshots_dir(root) / "text_structured_output_probe-1.4.0.json").exists()


def test_agent_script_registry_run_dry_run_does_not_execute_commands(capsys) -> None:
    exit_code = main(["run", "text_structured_output_probe", "--dry-run"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "DRY-RUN:" in captured.out
    assert "tests/test_text_structured_probe.py" in captured.out


def test_agent_ops_backend_smoke_script_runs_from_backend_cwd() -> None:
    root = backend_root()
    smoke_script = root / "agent_ops" / "tests" / "agent_ops_backend_smoke.py"

    completed = subprocess.run(
        [sys.executable, str(smoke_script)],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "backend agent_ops smoke flow passed" in completed.stdout


def test_agent_script_registry_rollback_restores_latest_stable_snapshot(tmp_path: Path) -> None:
    registry_dir = tmp_path / "agent_ops" / "registry"
    stable_dir = registry_dir / "stable"
    stable_dir.mkdir(parents=True)
    current = {
        "script_id": "sample_script",
        "version": "2.0.0",
        "status": "default",
        "notes": ["current"],
    }
    stable = {
        "script_id": "sample_script",
        "version": "1.0.0",
        "status": "default",
        "notes": ["stable"],
    }
    target = registry_dir / "sample_script.json"
    target.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
    (stable_dir / "sample_script-1.0.0.json").write_text(json.dumps(stable, ensure_ascii=False), encoding="utf-8")

    exit_code, message = rollback_record(tmp_path, "sample_script")

    assert exit_code == 0
    assert "stable 1.0.0" in message
    assert json.loads(target.read_text(encoding="utf-8"))["notes"] == ["stable"]


def test_validate_rejects_stale_stable_snapshot_with_same_version(tmp_path: Path) -> None:
    registry_dir = tmp_path / "agent_ops" / "registry"
    failure_dir = registry_dir / "failure-examples"
    stable_dir = registry_dir / "stable"
    failure_dir.mkdir(parents=True)
    stable_dir.mkdir()
    current = {
        "script_id": "sample_script",
        "version": "1.0.0",
        "status": "default",
        "owner": "test",
        "created_at": "2026-06-10",
        "updated_at": "2026-06-11",
        "summary": "current default",
        "working_directory": ".",
        "entrypoints": ["manual:temp"],
        "source_files": ["manual:temp"],
        "evidence": ["manual:temp"],
        "validation_commands": ["manual:temp"],
        "tests": ["manual:temp"],
        "failure_examples": ["agent_ops/registry/failure-examples/sample_failure.json"],
        "known_failures": ["temp_failure"],
        "rollback": ["restore stable"],
        "notes": ["current changed"],
    }
    stale = dict(current)
    stale["updated_at"] = "2026-06-10"
    stale["summary"] = "stale default"
    stale["notes"] = ["old stable snapshot"]
    failure = {
        "failure_id": "sample_failure",
        "script_id": "sample_script",
        "category": "script_error",
        "status": "documented",
        "observed_at": "2026-06-10",
        "summary": "temp",
        "input": {},
        "observed_output": {},
        "expected_behavior": "validate stale snapshot",
        "evidence": ["manual:temp"],
        "regression_tests": ["manual:temp"],
        "notes": ["temp"],
    }
    (registry_dir / "sample_script.json").write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
    (stable_dir / "sample_script-1.0.0.json").write_text(json.dumps(stale, ensure_ascii=False), encoding="utf-8")
    (failure_dir / "sample_failure.json").write_text(json.dumps(failure, ensure_ascii=False), encoding="utf-8")

    errors = validate_registry(tmp_path)

    assert errors == [
        "sample_script.json: stable snapshot differs from current default record: "
        "agent_ops/registry/stable/sample_script-1.0.0.json"
    ]


def test_agent_script_registry_run_expands_current_python_token(capsys) -> None:
    exit_code = main(["run", "agent_script_registry_flow", "--dry-run"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert sys.executable in captured.out
    assert "{python}" not in captured.out


def test_agent_ops_files_do_not_embed_local_machine_paths() -> None:
    root = backend_root() / "agent_ops"
    repair_root = repair_runs_dir(backend_root()).resolve()
    offenders: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".json", ".md", ".py"}:
            continue
        if path.resolve().is_relative_to(repair_root):
            continue
        text = path.read_text(encoding="utf-8")
        if LOCAL_ABSOLUTE_PATH_RE.search(text):
            offenders.append(path.relative_to(backend_root()).as_posix())

    assert offenders == []


def test_validate_rejects_local_absolute_paths_in_records(tmp_path: Path) -> None:
    command = "D" + r":\tools\python.exe -m pytest"
    _write_sample_registry(tmp_path, command)

    errors = validate_registry(tmp_path, require_current_snapshots=False)

    assert errors == [
        "sample_script.json: validation_commands must not contain a local absolute path: "
        + command
    ]


def test_validate_rejects_working_directory_escape(tmp_path: Path) -> None:
    target = _write_sample_registry(tmp_path, '{python} -c "raise SystemExit(0)"')
    data = json.loads(target.read_text(encoding="utf-8"))
    data["working_directory"] = ".."
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    errors = validate_registry(tmp_path, require_current_snapshots=False)

    assert errors == ["sample_script.json: working_directory must stay within backend root: .."]


def test_validate_rejects_registry_path_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside_agent_ops_escape.txt"
    outside.write_text("outside", encoding="utf-8")
    target = _write_sample_registry(tmp_path, '{python} -c "raise SystemExit(0)"')
    data = json.loads(target.read_text(encoding="utf-8"))
    data["source_files"] = ["../outside_agent_ops_escape.txt"]
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    errors = validate_registry(tmp_path, require_current_snapshots=False)

    assert errors == [
        "sample_script.json: source_files path must stay within backend root: ../outside_agent_ops_escape.txt"
    ]


def test_script_entrypoint_works_from_backend_cwd_without_parent_traversal() -> None:
    root = backend_root()
    script = root / "agent_ops" / "scripts" / "agent_script_registry.py"
    completed = subprocess.run(
        [sys.executable, str(script), "validate"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "agent script records validated" in completed.stdout


def _write_sample_registry(root: Path, command: str) -> Path:
    registry_dir = root / "agent_ops" / "registry"
    failure_dir = registry_dir / "failure-examples"
    stable_dir = registry_dir / "stable"
    failure_dir.mkdir(parents=True)
    stable_dir.mkdir(parents=True)
    current = {
        "script_id": "sample_script",
        "version": "1.0.1",
        "status": "default",
        "owner": "test",
        "created_at": "2026-06-10",
        "updated_at": "2026-06-10",
        "summary": "candidate",
        "working_directory": ".",
        "entrypoints": ["manual:temp"],
        "source_files": ["manual:temp"],
        "evidence": ["manual:temp"],
        "validation_commands": [command],
        "tests": ["manual:temp"],
        "failure_examples": ["agent_ops/registry/failure-examples/sample_failure.json"],
        "known_failures": ["temp_failure"],
        "rollback": ["restore stable"],
        "notes": ["candidate"],
    }
    stable = dict(current)
    stable["version"] = "1.0.0"
    stable["validation_commands"] = ['{python} -c "raise SystemExit(0)"']
    stable["notes"] = ["stable"]
    failure = {
        "failure_id": "sample_failure",
        "script_id": "sample_script",
        "category": "script_error",
        "status": "documented",
        "observed_at": "2026-06-10",
        "summary": "temp",
        "input": {},
        "observed_output": {},
        "expected_behavior": "fail then rollback",
        "evidence": ["manual:temp"],
        "regression_tests": ["manual:temp"],
        "notes": ["temp"],
    }
    target = registry_dir / "sample_script.json"
    target.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (stable_dir / "sample_script-1.0.0.json").write_text(
        json.dumps(stable, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (failure_dir / "sample_failure.json").write_text(
        json.dumps(failure, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def test_agent_script_registry_run_failure_rolls_back_unsnapshotted_candidate(tmp_path: Path) -> None:
    target = _write_sample_registry(tmp_path, '{python} -c "raise SystemExit(7)"')

    exit_code = main(["--root", str(tmp_path), "run", "sample_script", "--rollback-on-failure"])

    assert exit_code == 7
    assert json.loads(target.read_text(encoding="utf-8"))["version"] == "1.0.0"


def test_agent_script_registry_run_failure_starts_repair_agent_then_passes(tmp_path: Path) -> None:
    target = _write_sample_registry(tmp_path, '{python} -c "raise SystemExit(7)"')
    repair_agent = tmp_path / "fake_repair_agent.py"
    repair_agent.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "import sys",
                "from pathlib import Path",
                "task = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))",
                "root = Path(sys.argv[1]).resolve().parents[2]",
                "record_path = root / task['registry_record_path']",
                "record = json.loads(record_path.read_text(encoding='utf-8'))",
                "record['validation_commands'] = ['{python} -c \"raise SystemExit(0)\"']",
                "record['notes'] = ['repaired by fake agent']",
                "record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + chr(10), encoding='utf-8')",
                "print('fake repair agent completed')",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    agent_command = "{python} " + subprocess.list2cmdline([str(repair_agent)]) + " {repair_task}"

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "run",
            "sample_script",
            "--repair-on-failure",
            "--agent-command",
            agent_command,
            "--snapshot-on-success",
        ]
    )

    assert exit_code == 0
    assert json.loads(target.read_text(encoding="utf-8"))["notes"] == ["repaired by fake agent"]
    assert (repair_runs_dir(tmp_path)).exists()
    assert (stable_snapshots_dir(tmp_path) / "sample_script-1.0.1.json").exists()


def test_repair_agent_rejects_changes_outside_allowlist(tmp_path: Path, capsys) -> None:
    _write_sample_registry(tmp_path, '{python} -c "raise SystemExit(7)"')
    (tmp_path / "lib").mkdir()
    repair_agent = tmp_path / "bad_repair_agent.py"
    repair_agent.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "Path('lib/outside.txt').write_text('bad', encoding='utf-8')",
                "print('bad repair agent completed')",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    agent_command = "{python} " + subprocess.list2cmdline([str(repair_agent)]) + " {repair_task}"

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "run",
            "sample_script",
            "--repair-on-failure",
            "--agent-command",
            agent_command,
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "outside repair_write_allowlist" in captured.out
    assert "lib/outside.txt" in captured.out
    assert "changes restored" in captured.out
    assert not (tmp_path / "lib" / "outside.txt").exists()


def test_repair_agent_rejects_and_restores_backend_external_changes(tmp_path: Path, capsys) -> None:
    repo_root = tmp_path / "repo"
    backend = repo_root / "backend"
    backend.mkdir(parents=True)
    (repo_root / "manifest.json").write_text("original", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True)
    _write_sample_registry(backend, '{python} -c "raise SystemExit(7)"')
    repair_agent = backend / "bad_repair_agent.py"
    repair_agent.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "Path('../manifest.json').write_text('bad', encoding='utf-8')",
                "print('bad repair agent completed')",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    agent_command = "{python} " + subprocess.list2cmdline([str(repair_agent)]) + " {repair_task}"

    exit_code = main(
        [
            "--root",
            str(backend),
            "run",
            "sample_script",
            "--repair-on-failure",
            "--agent-command",
            agent_command,
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "../manifest.json" in captured.out
    assert "changes restored" in captured.out
    assert (repo_root / "manifest.json").read_text(encoding="utf-8") == "original"


def test_agent_script_registry_run_success_can_snapshot_candidate(tmp_path: Path) -> None:
    _write_sample_registry(tmp_path, '{python} -c "raise SystemExit(0)"')

    exit_code = main(["--root", str(tmp_path), "run", "sample_script", "--snapshot-on-success"])

    assert exit_code == 0
    assert (stable_snapshots_dir(tmp_path) / "sample_script-1.0.1.json").exists()
