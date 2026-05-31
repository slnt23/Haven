"""输出格式化工具。"""

from __future__ import annotations


def format_table(rows: list[dict], headers: list[str] | None = None) -> str:
    """纯文本表格。供 JSON 输出外的场景使用。"""
    if not rows:
        return "(empty)"
    keys = headers or list(rows[0].keys())
    widths = {k: max(len(k), max(len(str(r.get(k, ""))) for r in rows)) for k in keys}
    sep = "+" + "+".join("-" * (w + 2) for w in widths.values()) + "+"
    header = "|" + "|".join(f" {k:<{widths[k]}} " for k in keys) + "|"
    lines = [sep, header, sep]
    for row in rows:
        line = "|" + "|".join(f" {str(row.get(k, '')):<{widths[k]}} " for k in keys) + "|"
        lines.append(line)
    lines.append(sep)
    return "\n".join(lines)


def format_kv(pairs: list[tuple[str, str]], indent: int = 2) -> str:
    """键值对格式化。"""
    prefix = " " * indent
    max_key = max(len(k) for k, _ in pairs) if pairs else 0
    return "\n".join(f"{prefix}{k:<{max_key}}  {v}" for k, v in pairs)


def format_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds*1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}m{secs}s"


def format_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes}B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes/1024:.1f}KB"
    return f"{num_bytes/(1024*1024):.1f}MB"


def truncate(text: str, max_len: int = 80, suffix: str = "...") -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - len(suffix)] + suffix
