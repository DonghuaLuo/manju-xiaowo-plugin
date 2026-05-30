"""分集切分共享工具函数。"""


def count_chars(text: str) -> int:
    """非空白 Unicode 字符总数。"""
    return sum(1 for c in text if not c.isspace())


def find_char_offset(text: str, target_count: int) -> int:
    """将有效字符数转换为原文字符偏移位置。"""
    counted = 0
    lines = text.split("\n")
    pos = 0

    for line_idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            pos += len(line)
            if line_idx < len(lines) - 1:
                pos += 1
            continue

        for char in line:
            if not char.strip():
                pos += 1
                continue
            counted += 1
            if counted >= target_count:
                return pos
            pos += 1

        if line_idx < len(lines) - 1:
            pos += 1

    return pos


_ZH_SENTENCE_ENDINGS = frozenset({"。", "！", "？", "…"})
_LATIN_SENTENCE_ENDINGS = frozenset({".", "!", "?", "…"})


def find_natural_breakpoints(
    text: str,
    center_offset: int,
    window: int = 200,
    language: str | None = None,
) -> list[dict]:
    """在指定偏移附近查找自然断点。"""
    start = max(0, center_offset - window)
    end = min(len(text), center_offset + window)
    code = (language or "").strip().lower()
    sentence_endings = _LATIN_SENTENCE_ENDINGS if code in ("en", "vi") else _ZH_SENTENCE_ENDINGS
    breakpoints = []

    for i in range(start, end):
        ch = text[i]
        if ch == "\n" and i + 1 < len(text) and text[i + 1] == "\n":
            breakpoints.append(
                {
                    "offset": i + 1,
                    "char": "\\n\\n",
                    "type": "paragraph",
                    "distance": abs(i + 1 - center_offset),
                }
            )
        elif ch in sentence_endings:
            breakpoints.append(
                {
                    "offset": i + 1,
                    "char": ch,
                    "type": "sentence",
                    "distance": abs(i + 1 - center_offset),
                }
            )

    breakpoints.sort(key=lambda bp: bp["distance"])
    return breakpoints
