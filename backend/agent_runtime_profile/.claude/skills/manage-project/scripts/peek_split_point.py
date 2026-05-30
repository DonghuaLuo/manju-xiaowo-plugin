#!/usr/bin/env python3
"""探测分集切分点附近上下文。"""

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _text_utils import count_chars, find_natural_breakpoints  # noqa: E402

_ZH_UNIT_PATTERN = re.compile("[㐀-鿿豈-﫿　-〿＀-￯𠀀-𲎯]")
_LATIN_WORD_PATTERN = re.compile(r"\b\w+\b", re.UNICODE)
_SUPPORTED_LANGUAGES = ("zh", "en", "vi")


def _pattern_for(language: str | None) -> "re.Pattern[str]":
    code = (language or "").strip().lower()
    if code in ("en", "vi"):
        return _LATIN_WORD_PATTERN
    return _ZH_UNIT_PATTERN


def count_reading_units(text: str, language: str | None) -> int:
    if not text:
        return 0
    return len(_pattern_for(language).findall(text))


def find_reading_unit_offset(text: str, target_units: int, language: str | None) -> int:
    if target_units <= 0 or not text:
        return 0
    count = 0
    for match in _pattern_for(language).finditer(text):
        count += 1
        if count >= target_units:
            return match.end()
    return len(text)


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
    source_path = (cwd / arg_source).resolve() if not Path(arg_source).is_absolute() else Path(arg_source).resolve()
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


def main():
    parser = argparse.ArgumentParser(description="探测切分点附近上下文")
    parser.add_argument("--source", required=True, help="源文件路径")
    parser.add_argument("--target", required=True, type=int, help="目标阅读单位数")
    parser.add_argument("--context", default=200, type=int, help="上下文字符数")
    parser.add_argument("--language", default=None, help="阅读单位语言(zh/en/vi)")
    args = parser.parse_args()

    if args.target < 1:
        print(f"❌ --target ({args.target}) 必须 >= 1", file=sys.stderr)
        sys.exit(1)

    source_path = _resolve_source_in_project(args.source)
    language = _resolve_language(args.language)
    text = unicodedata.normalize("NFC", source_path.read_text(encoding="utf-8"))
    total_units = count_reading_units(text, language)

    if total_units == 0:
        print(f"❌ 源文件无可计阅读单位(language={language}): {source_path}", file=sys.stderr)
        sys.exit(1)
    if args.target >= total_units:
        print(f"错误:目标阅读单位 ({args.target}) 超过或等于总阅读单位 ({total_units})", file=sys.stderr)
        sys.exit(1)

    target_offset = find_reading_unit_offset(text, args.target, language)
    split_target_chars = count_chars(text[:target_offset])
    breakpoints = find_natural_breakpoints(text, target_offset, window=args.context, language=language)

    ctx_start = max(0, target_offset - args.context)
    ctx_end = min(len(text), target_offset + args.context)
    result = {
        "source": str(source_path),
        "language": language,
        "total_units": total_units,
        "target_units": args.target,
        "split_target_chars": split_target_chars,
        "target_offset": target_offset,
        "context_before": text[ctx_start:target_offset],
        "context_after": text[target_offset:ctx_end],
        "nearby_breakpoints": breakpoints[:10],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
