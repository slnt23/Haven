"""Capability 层 —— 统一的能力管理。

提供:
  - Capability / Tool / Skill — 统一的能力接口
  - CapabilityRegistry — 统一注册表（Tool + Skill 共用）
  - DependencyResolver — Skill 依赖传递闭包解析
  - CapabilityLoader / SkillLoader — 能力加载
  - ToolProvider — 工具来源抽象
"""

from haven.capability.models import Capability, CapabilityMetadata, Skill, Tool
from haven.capability.registry import CapabilityRegistry
from haven.capability.resolver import DependencyResolver
from haven.capability.loader import CapabilityLoader, SkillLoader

__all__ = [
    "Capability",
    "CapabilityMetadata",
    "Tool",
    "Skill",
    "CapabilityRegistry",
    "DependencyResolver",
    "CapabilityLoader",
    "SkillLoader",
]
