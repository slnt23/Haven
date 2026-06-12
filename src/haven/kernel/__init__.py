"""Haven Kernel —— 框架基础设施层。

提供：
  - AgentEvent / EventType：统一事件系统
  - TraceContext：分布式追踪
  - HavenCallbackHandler：LangChain 回调桥接
  - 异常体系：HavenError 及其子类
  - LifecycleManager：进程生命周期管理
"""

from haven.kernel.callbacks import HavenCallbackHandler
from haven.kernel.errors import (
    ConfigError,
    ExecutionError,
    HavenError,
    KernelError,
    LifecycleError,
    MemoryError,
    ModelError,
    SkillError,
    ToolError,
)
from haven.kernel.event import AgentEvent, EventType
from haven.kernel.lifecycle import LifecycleHook, LifecycleManager
from haven.kernel.trace import (
    TraceContext,
    config_with_trace,
    get_current_trace,
    reset_current_trace,
    set_current_trace,
    trace_id_from_config,
)

__all__ = [
    # Event
    "AgentEvent",
    "EventType",
    # Trace
    "TraceContext",
    "set_current_trace",
    "get_current_trace",
    "config_with_trace",
    "trace_id_from_config",
    # Callbacks
    "HavenCallbackHandler",
    # Errors
    "HavenError",
    "KernelError",
    "ConfigError",
    "ModelError",
    "LifecycleError",
    "ToolError",
    "SkillError",
    "MemoryError",
    "ExecutionError",
    # Lifecycle
    "LifecycleHook",
    "LifecycleManager",
]
