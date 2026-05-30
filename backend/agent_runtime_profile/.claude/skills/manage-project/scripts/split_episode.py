#!/usr/bin/env python3
"""执行分集切分。"""

import argparse
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _text_utils import find_char_offset  # noqa: E402


def _resolve_source_in_project(arg_source: str) -> tuple[Path, Path]:
    cwd = Path.cwd().resolve()
    if not (cwd / "project.json").is_file():
        print(f"❌ 必须在项目目录内运行（当前 cwd={cwd} 不含 project.json）", file=sys.stderr)
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
        print(f"❌ 源文件必须位于 {source_dir} 内，收到: {source_path}", file=sys.stderr)
        sys.exit(1)
    if not source_path.is_file():
        print(f"❌ 源文件不存在或不是普通文件: {source_path}", file=sys.stderr)
        sys.exit(1)
    return source_path, source_dir


def find_anchor_near_target(text: str, anchor: str, target_offset: int, window: int = 500) -> list[int]:
    search_start = max(0, target_offset - window)
    search_end = min(len(text), target_offset + window)
    search_region = text[search_start:search_end]
    positions = []
    start = 0
    while True:
        idx = search_region.find(anchor, start)
        if idx == -1:
            break
        positions.append(search_start + idx + len(anchor))
        start = idx + 1
    positions.sort(key=lambda p: abs(p - target_offset))
    return positions


def _positive_int(value: str) -> int:
    ivalue = int(value)
    if ivalue <= 0:
        raise argparse.ArgumentTypeError(f"必须是正整数，收到: {value}")
    return ivalue


def main():
    parser = argparse.ArgumentParser(description="执行分集切分")
    parser.add_argument("--source", required=True, help="源文件路径")
    parser.add_argument("--episode", required=True, type=_positive_int, help="集数编号")
    parser.add_argument("--target", required=True, type=int, help="目标字符数，使用 peek 输出的 split_target_chars")
    parser.add_argument("--anchor", required=True, help="切分点前的文本片段")
    parser.add_argument("--context", default=500, type=int, help="搜索窗口大小")
    parser.add_argument("--dry-run", action="store_true", help="仅展示切分预览，不写文件")
    args = parser.parse_args()

    source_path, source_dir = _resolve_source_in_project(args.source)
    text = unicodedata.normalize("NFC", source_path.read_text(encoding="utf-8"))
    target_offset = find_char_offset(text, args.target)
    positions = find_anchor_near_target(text, args.anchor, target_offset, window=args.context)

    if len(positions) == 0:
        print(f'错误：在目标字数 {args.target} 附近未找到锚点文本: "{args.anchor}"', file=sys.stderr)
        sys.exit(1)

    if len(positions) > 1:
        print(f"警告：锚点文本在窗口内匹配到 {len(positions)} 处，使用距离目标最近的匹配。", file=sys.stderr)

    split_pos = positions[0]
    part_before = text[:split_pos]
    part_after = text[split_pos:]

    preview_len = 50
    print(f"目标字数: {args.target}，目标偏移: {target_offset}")
    print(f"切分位置: 第 {split_pos} 字符处")
    print(f"前文末尾: ...{part_before[-preview_len:]}")
    print(f"后文开头: {part_after[:preview_len]}...")
    print(f"前半部分: {len(part_before)} 字符")
    print(f"后半部分: {len(part_after)} 字符")

    if args.dry_run:
        print("\n[Dry Run] 未写入文件。确认无误后去掉 --dry-run 参数执行。")
        return

    episode_file = source_dir / f"episode_{args.episode}.txt"
    remaining_file = source_dir / "_remaining.txt"
    episode_file.write_text(part_before, encoding="utf-8")
    remaining_file.write_text(part_after, encoding="utf-8")
    print("\n已生成:")
    print(f"  {episode_file} ({len(part_before)} 字符)")
    print(f"  {remaining_file} ({len(part_after)} 字符)")
    print(f"  原文件未修改: {source_path}")


if __name__ == "__main__":
    main()
