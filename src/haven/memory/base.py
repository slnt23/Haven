"""Memory 基础类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class MemoryItem:
    """统一记忆条目，所有存储层共用。"""

    id: str
    content: str
    memory_type: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    importance: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)
