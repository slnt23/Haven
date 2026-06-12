"""Haven 异常体系。

所有框架级异常继承自 HavenError，区分 Kernel / Config / Model 等层级，
便于上层针对性捕获和处理。
"""

from __future__ import annotations


class HavenError(Exception):
    """Haven 框架所有异常的基类。

    上层可安全捕获此类以兜底所有框架异常。
    """


# ============================================================================
# Kernel 层异常
# ============================================================================


class KernelError(HavenError):
    """Kernel 层级异常基类。"""


class ConfigError(KernelError):
    """配置加载、校验失败。"""


class ModelError(KernelError):
    """模型创建、调用失败。"""


class LifecycleError(KernelError):
    """生命周期钩子执行失败。"""


# ============================================================================
# 通用异常
# ============================================================================


class ToolError(HavenError):
    """工具调用、注册失败。"""


class SkillError(HavenError):
    """Skill 加载、解析失败。"""


class MemoryError(HavenError):
    """记忆存储、提取失败。"""


class ExecutionError(HavenError):
    """执行管道中的错误。"""
