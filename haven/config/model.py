"""模型配置（`config/model.yaml`）的加载器。

与 `config/mcp.py` 不同：本模块只被 `settings.py` 消费（pydantic 环境），
不需要标准库约束，直接使用 PyYAML。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_MODEL_FILE = Path(__file__).resolve().parent / "model.yaml"
#: 默认模型（MDA 格式 <provider>:<model>）
DEFAULT_AGENT_MODEL = "deepseek:deepseek-v4-flash"


def _load_raw() -> dict[str, Any]:
    """加载 model.yaml 原始数据；文件缺失/空/非 dict → 返回 {}。"""
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


@lru_cache(maxsize=1)
def load_model_params() -> dict[str, Any]:
    """加载推理参数（`model.params` 子节点）；文件缺失或空 → 返回 {}（全部走默认值）。"""
    raw = _load_raw()
    model_node = raw.get("model")
    if isinstance(model_node, dict):
        params = model_node.get("params")
        if isinstance(params, dict):
            return {str(k): v for k, v in params.items() if v is not None}
    return {}


@lru_cache(maxsize=1)
def load_model_name() -> str:
    """加载模型名称（`model.name`）；YAML 未写或缺失 → 返回 DEFAULT_AGENT_MODEL。"""
    raw = _load_raw()
    model_node = raw.get("model")
    if isinstance(model_node, dict):
        name = model_node.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return DEFAULT_AGENT_MODEL