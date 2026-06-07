"""工具元数据 —— 附加在每个工具上的轻量级描述信息。

刻意不包含分类（category）、权限（permissions）、标签（tags）等字段。
工具选择完全由 LLM Function Calling 根据 name + description 完成，
不需要框架层做语义匹配或权限过滤。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ToolMetadata(BaseModel):
    """工具的声明式元数据，仅用于追踪和审计。

    字段说明：
      - provider: 来源提供者名称（如 "builtin"、"mcp:github"）
      - version: 工具版本号
      - requires_confirmation: 高风险操作是否需要用户二次确认
      - timeout_seconds: 单次调用超时时间
    """

    provider: str = ""  # 所属提供者，如 "builtin" 或 "mcp:filesystem"
    version: str = "1.0"  # 工具版本
    requires_confirmation: bool = False  # 是否需要用户确认（如文件删除）
    timeout_seconds: int = 30  # 默认超时
