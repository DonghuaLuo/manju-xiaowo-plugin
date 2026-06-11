from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_SCRIPT = BACKEND_ROOT / "agent_ops" / "scripts" / "agent_script_registry.py"


@dataclass(frozen=True)
class AgentOpsSmokeAgent:
    python: str
    cwd: Path

    def run_registry(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.python, str(REGISTRY_SCRIPT), *args],
            cwd=self.cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )


def _assert_ok(completed: subprocess.CompletedProcess[str]) -> str:
    output = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode != 0:
        raise AssertionError(output)
    return output


def _write_repair_fixture(root: Path) -> None:
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
        "updated_at": "2026-06-11",
        "summary": "repair flow fixture",
        "working_directory": ".",
        "entrypoints": ["manual:temp"],
        "source_files": ["manual:temp"],
        "evidence": ["manual:temp"],
        "validation_commands": ['{python} -c "raise SystemExit(7)"'],
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
        "expected_behavior": "fail then repair",
        "evidence": ["manual:temp"],
        "regression_tests": ["manual:temp"],
        "notes": ["temp"],
    }
    (registry_dir / "sample_script.json").write_text(
        json.dumps(current, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (stable_dir / "sample_script-1.0.0.json").write_text(
        json.dumps(stable, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (failure_dir / "sample_failure.json").write_text(
        json.dumps(failure, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_fake_repair_agent(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "import sys",
                "from pathlib import Path",
                "task_path = Path(sys.argv[1])",
                "task = json.loads(task_path.read_text(encoding='utf-8'))",
                "root = task_path.resolve().parents[2]",
                "record_path = root / task['registry_record_path']",
                "record = json.loads(record_path.read_text(encoding='utf-8'))",
                "record['validation_commands'] = ['{python} -c \"raise SystemExit(0)\"']",
                "record['notes'] = ['repaired by smoke agent']",
                "record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + chr(10), encoding='utf-8')",
                "print('fake repair agent completed')",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    agent = AgentOpsSmokeAgent(python=sys.executable, cwd=BACKEND_ROOT)

    validate_output = _assert_ok(agent.run_registry("validate"))
    if "agent script records validated" not in validate_output:
        raise AssertionError(validate_output)

    list_output = _assert_ok(agent.run_registry("list"))
    for script_id in (
        "agent_script_registry_flow",
        "custom_provider_model_discovery",
        "text_structured_output_probe",
    ):
        if script_id not in list_output:
            raise AssertionError(list_output)

    examples_output = _assert_ok(agent.run_registry("failure-examples"))
    if "text_structured_output_probe_schema_not_enforced" not in examples_output:
        raise AssertionError(examples_output)

    dry_run_output = _assert_ok(agent.run_registry("run", "--all-defaults", "--dry-run"))
    if "DRY-RUN:" not in dry_run_output or sys.executable not in dry_run_output:
        raise AssertionError(dry_run_output)

    with tempfile.TemporaryDirectory() as raw_temp:
        temp_root = Path(raw_temp)
        _write_repair_fixture(temp_root)
        fake_agent = temp_root / "fake_repair_agent.py"
        _write_fake_repair_agent(fake_agent)
        agent_command = "{python} " + subprocess.list2cmdline([str(fake_agent)]) + " {repair_task}"
        repair_output = _assert_ok(
            agent.run_registry(
                "--root",
                str(temp_root),
                "run",
                "sample_script",
                "--repair-on-failure",
                "--agent-command",
                agent_command,
                "--snapshot-on-success",
            )
        )
        for marker in ("REPAIR-TASK:", "REPAIR-AGENT:", "fake repair agent completed", "wrote stable snapshot"):
            if marker not in repair_output:
                raise AssertionError(repair_output)

    print("OK: backend agent_ops smoke flow passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
