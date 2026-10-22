"""模型推理参数（`config/model.yaml`）的加载器。

与 `config/mcp.py` 不同：本模块只被 `settings.py` 消费（pydantic 环境），
不需要标准库约束，直接使用 PyYAML。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_MODEL_FILE = Path(__file__).resolve().parent / "model.yaml"


@lru_cache(maxsize=1)
def load_model_params() -> dict[str, Any]:
    """加载 model.yaml；文件缺失或空 → 返回 {}（全部走 AgentModelSettings 默认值）。"""
    try:
        text = _MODEL_FILE.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.strip():
        return {}
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        return {}
    return {str(k): v for k, v in data.items() if v is not None}