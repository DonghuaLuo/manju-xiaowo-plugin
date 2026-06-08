#!/usr/bin/env python3
"""输出 source/ 下文本文件的安全统计信息。"""

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _text_utils import count_chars  # noqa: E402

_ZH_UNIT_PATTERN = re.compile("[㐀-鿿豈-﫿　-〿＀-￯𠀀-𲎯]")
_LATIN_WORD_PATTERN = re.compile(r"\b\w+\b", re.UNICODE)
_SUPPORTED_LANGUAGES = ("zh", "en", "vi")


def _pattern_for(language: str | None) -> "re.Pattern[str]":
    code = (language or "").strip().lower()
    if code in ("en", "vi"):
        return _LATIN_WORD_PATTERN
    return _ZH_UNIT_PATTERN


def _count_reading_units(text: str, language: str | None) -> int:
    if not text:
        return 0
    return len(_pattern_for(language).findall(text))


def _resolve_source_in_project(arg_source: str) -> Path:
    cwd = Path.cwd().resolve()
    if not (cwd / "project.json").is_file():
        print(f"❌ 必须在项目目录内运行(当前 cwd={cwd} 不含 project.json)", file=sys.stderr)
        sys.exit(1)

    source_dir_unresolved = cwd / "source"
    if source_dir_unresolved.is_symlink():
        print(f"❌ source/ 不能是符号链接: {source_dir_unresolved}", file=sys.stderr)
        sys.exit(1)

    source_dir = source_dir_unresolved.resolve()
    if not source_dir.is_dir():
        print(f"❌ 项目缺 source/ 目录: {source_dir}", file=sys.stderr)
        sys.exit(1)

    raw_source = Path(arg_source)
    source_path = raw_source.resolve() if raw_source.is_absolute() else (cwd / raw_source).resolve()
    if not source_path.is_relative_to(source_dir):
        print(f"❌ 源文件必须位于 {source_dir} 内,收到: {source_path}", file=sys.stderr)
        sys.exit(1)
    if not source_path.is_file():
        print(f"❌ 源文件不存在或不是普通文件: {source_path}", file=sys.stderr)
        sys.exit(1)
    return source_path


def _resolve_language(cli_arg: str | None) -> str:
    raw: str | None = cli_arg
    if raw is None:
        project_json = Path.cwd().resolve() / "project.json"
        if project_json.is_file():
            try:
                data = json.loads(project_json.read_text(encoding="utf-8"))
                stored = data.get("source_language")
                raw = str(stored) if stored else None
            except (json.JSONDecodeError, OSError):
                raw = None
    if raw is None:
        return "zh"
    normalized = raw.strip().lower()
    if normalized not in _SUPPORTED_LANGUAGES:
        print(f"❌ 不支持的 language={raw!r}(可选: {list(_SUPPORTED_LANGUAGES)})", file=sys.stderr)
        sys.exit(1)
    return normalized


def _line_count(text: str) -> int:
    if text == "":
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="输出 source 文本文件的安全统计信息")
    parser.add_argument("--source", required=True, help="源文件路径，如 source/novel.txt 或 source/_remaining.txt")
    parser.add_argument("--language", default=None, help="阅读单位语言(zh/en/vi)")
    args = parser.parse_args()

    source_path = _resolve_source_in_project(args.source)
    language = _resolve_language(args.language)
    text = unicodedata.normalize("NFC", source_path.read_text(encoding="utf-8"))
    result = {
        "source": str(source_path),
        "language": language,
        "file_size_bytes": source_path.stat().st_size,
        "line_count": _line_count(text),
        "nonempty_line_count": sum(1 for line in text.splitlines() if line.strip()),
        "char_count": len(text),
        "non_whitespace_char_count": count_chars(text),
        "reading_units": _count_reading_units(text, language),
        "has_trailing_newline": text.endswith("\n"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
