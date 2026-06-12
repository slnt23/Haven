"""公共类型定义 —— StreamChunk 流式管道数据块。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(slots=True)
class StreamChunk:
    """流式管道中的单个产出。

    kind="text"    — LLM 输出的 token 文本
    kind="status"  — 进度/状态消息（工具调用、步骤进度等）
    kind="plan"    — 规划摘要（意图 + Agent + 复杂度）
    """

    kind: Literal["text", "status", "plan"]
    content: str
