"""按源文语言计阅读单位的轻量度量工具。"""

from __future__ import annotations

import re

_ZH_UNIT_PATTERN = re.compile("[㐀-鿿豈-﫿　-〿＀-￯𠀀-𲎯]")
_LATIN_WORD_PATTERN = re.compile(r"\b\w+\b", re.UNICODE)


def _pattern_for(language: str | None) -> re.Pattern[str]:
    code = (language or "").strip().lower()
    if code in ("en", "vi"):
        return _LATIN_WORD_PATTERN
    return _ZH_UNIT_PATTERN


def count_reading_units(text: str, language: str | None) -> int:
    """按源文语言数阅读单位。

    zh: 汉字 + CJK 标点 / 全角符号。
    en / vi: Unicode word-boundary 词数。
    未知 / None / 空 language: 按 zh 处理，兼容旧项目。
    """
    if not text:
        return 0
    return len(_pattern_for(language).findall(text))


def find_reading_unit_offset(text: str, target_units: int, language: str | None) -> int:
    """返回第 target_units 个阅读单位末尾的字符偏移。"""
    if target_units <= 0 or not text:
        return 0
    count = 0
    for match in _pattern_for(language).finditer(text):
        count += 1
        if count >= target_units:
            return match.end()
    return len(text)
