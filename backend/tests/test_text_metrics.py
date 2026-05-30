"""阅读单位度量与 agent 分集脚本的同步测试。"""

from __future__ import annotations

import importlib.util
import unicodedata
from pathlib import Path

from lib.text_metrics import count_reading_units, find_reading_unit_offset


def _load_peek_module():
    backend_root = Path(__file__).resolve().parents[1]
    script = backend_root / "agent_runtime_profile" / ".claude" / "skills" / "manage-project" / "scripts" / "peek_split_point.py"
    spec = importlib.util.spec_from_file_location("_manju_peek_split_point", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_zh_counts_cjk_and_sip_plane_chars() -> None:
    text = f"今天{chr(0x20000)}天气{chr(0x30000)}好"
    assert count_reading_units(text, "zh") == 7


def test_en_and_vi_count_words() -> None:
    assert count_reading_units("The quick brown fox", "en") == 4
    assert count_reading_units("Hôm nay trời đẹp quá", "vi") == 5


def test_find_reading_unit_offset_scans_in_text_order() -> None:
    text = "intro filler filler target end"
    assert find_reading_unit_offset(text, 4, "en") == len("intro filler filler target")


def test_vi_callers_must_normalize_nfc() -> None:
    nfc = "Hôm nay trời"
    nfd = unicodedata.normalize("NFD", nfc)
    assert count_reading_units(nfc, "vi") == 3
    assert count_reading_units(nfd, "vi") > 3
    assert count_reading_units(unicodedata.normalize("NFC", nfd), "vi") == 3


def test_peek_vendor_metrics_stay_in_sync() -> None:
    peek = _load_peek_module()
    samples = [
        ("你好世界", "zh"),
        (f"今{chr(0x20000)}天", "zh"),
        ("hello world", "en"),
        ("Hôm nay trời", "vi"),
        ("안녕하세요", "zh"),
    ]

    assert peek._ZH_UNIT_PATTERN.pattern == count_reading_units.__globals__["_ZH_UNIT_PATTERN"].pattern
    assert peek._LATIN_WORD_PATTERN.pattern == count_reading_units.__globals__["_LATIN_WORD_PATTERN"].pattern
    for text, lang in samples:
        assert peek.count_reading_units(text, lang) == count_reading_units(text, lang)
        assert peek.find_reading_unit_offset(text, 2, lang) == find_reading_unit_offset(text, 2, lang)
