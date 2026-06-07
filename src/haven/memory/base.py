"""记忆基础类型 —— 统一的记忆条目。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MemoryItem:
    """统一记忆条目。

    字段说明：
      - content:      自然语言事实句子
      - entity_name:  所属实体（用户标识）
      - importance:   重要性 0.0~1.0
      - source:       来源标识（如 episode_id、session_id）
      - created_at:   创建时间
    """

    content: str
    entity_name: str = ""
    importance: float = 0.5
    source: str = ""
    created_at: datetime = field(default_factory=datetime.now)
