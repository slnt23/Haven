"""Prompt 加载器 —— 读取 .md 文件，解析 YAML 头 + Markdown 正文。

文件格式：
    ---
    name: greeting
    description: 打招呼场景
    temperature: 0.7
    ---

    # 场景
    用户正在打招呼...

用法：
    from haven.llm.prompts import load_prompt, load_skill

    body = load_prompt("greeting")          # 只拿正文（发给 LLM）
    meta = load_skill("greeting")           # 拿元数据 + 正文
    print(meta["temperature"])              # 0.7
"""

from pathlib import Path
from typing import Any

import yaml

_PROMPT_DIR = Path(__file__).parent
_cache: dict[str, dict[str, Any]] = {}


def _parse_md(filepath: Path) -> dict[str, Any]:
    raw = filepath.read_text(encoding="utf-8")
    meta: dict[str, Any] = {}
    body = raw

    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            meta = yaml.safe_load(parts[1]) or {}
            body = parts[2].strip()
    else:
        meta = {"name": filepath.stem}

    meta["_body"] = body
    return meta


def load_skill(name: str) -> dict[str, Any]:
    if name not in _cache:
        path = _PROMPT_DIR / f"{name}.md"
        if path.exists():
            _cache[name] = _parse_md(path)
        else:
            _cache[name] = {"name": name, "_body": ""}
    return _cache[name]


def load_prompt(name: str) -> str:
    return load_skill(name).get("_body", "")


def reload_prompts() -> None:
    _cache.clear()