from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))

from lib.script_generator import ScriptGenerator  # noqa: E402
from lib.text_backends.base import TextGenerationResult  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: dict) -> None:
    _write(path, json.dumps(payload, ensure_ascii=False, indent=2))


def _write_basic_drama_project(project_path: Path) -> None:
    _write_json(
        project_path / "project.json",
        {
            "title": "烟测项目",
            "content_mode": "drama",
            "overview": {},
            "characters": {},
            "scenes": {},
            "props": {},
            "style": "写实",
            "style_description": "cinematic",
            "_supported_durations": [4, 6, 8],
        },
    )
    _write(
        project_path / "drafts" / "episode_1" / "step1_normalized_script.md",
        "| scene_id | scene_description | duration_seconds | segment_break |\n"
        "| --- | --- | --- | --- |\n"
        "| E1S01 | 场景 | 4 | 是 |\n",
    )


def _valid_drama_script_payload() -> dict:
    return {
        "title": "第一集",
        "content_mode": "drama",
        "scenes": [
            {
                "scene_id": "E1S01",
                "duration_seconds": 4,
                "segment_break": True,
                "characters_in_scene": [],
                "scenes": [],
                "props": [],
                "image_prompt": {
                    "scene": "林清站在雨夜巷口，路灯从左侧打出冷白光，地面积水倒映她的身影。",
                    "composition": {
                        "shot_type": "Medium Shot",
                        "lighting": "左侧冷白路灯照亮半身，背景保持暗部层次",
                        "ambiance": "雨丝和薄雾在路灯下可见",
                    },
                },
                "video_prompt": {
                    "action": "林清缓慢抬头，手指收紧伞柄，雨水沿伞缘滴落。",
                    "camera_motion": "Static",
                    "ambiance_audio": "雨声和远处脚步声",
                    "dialogue": [],
                },
            }
        ],
    }


class _PreflightFailsGenerator:
    model = "fake-model"

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.requests = []

    async def ensure_structured_output_ready(self):
        raise ValueError("probe failed before script generation")

    async def generate(self, request, project_name=None):
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self.responses) - 1)
        return TextGenerationResult(text=self.responses[index], provider="fake", model="fake-model")


async def _assert_non_strict_retry_passes(temp_root: Path) -> None:
    project_path = temp_root / "retry-passes"
    _write_basic_drama_project(project_path)
    fake = _PreflightFailsGenerator(
        [
            "not json",
            json.dumps(_valid_drama_script_payload(), ensure_ascii=False),
        ]
    )

    output = await ScriptGenerator(project_path, generator=fake).generate(1)
    payload = json.loads(output.read_text(encoding="utf-8"))

    if payload["scenes"][0]["scene_id"] != "E1S01":
        raise AssertionError("generated scene id does not match Step 1")
    if payload["metadata"]["structured_output_mode"] != "non_strict_validated":
        raise AssertionError("fallback mode metadata missing")
    if payload["metadata"]["structured_output_attempts"] != 2:
        raise AssertionError("retry attempt count was not recorded")
    if any(request.response_schema is not None for request in fake.requests):
        raise AssertionError("non-strict fallback still sent response_schema")


async def _assert_invalid_non_strict_never_writes(temp_root: Path) -> None:
    project_path = temp_root / "invalid-never-writes"
    _write_basic_drama_project(project_path)
    fake = _PreflightFailsGenerator(["not json", "[]", '{"title":"bad","scenes":[]}'])

    try:
        await ScriptGenerator(project_path, generator=fake).generate(1)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid non-strict output unexpectedly passed")

    if len(fake.requests) != 3:
        raise AssertionError("invalid non-strict output did not retry three times")
    if (project_path / "scripts" / "episode_1.json").exists():
        raise AssertionError("invalid non-strict output was written to disk")


async def _main_async() -> None:
    with tempfile.TemporaryDirectory(prefix="manju-text-structured-smoke-") as raw:
        temp_root = Path(raw)
        await _assert_non_strict_retry_passes(temp_root)
        await _assert_invalid_non_strict_never_writes(temp_root)


def main() -> int:
    asyncio.run(_main_async())
    print("OK: text structured output fallback smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
