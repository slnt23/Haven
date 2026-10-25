"""工具权限登记表 —— 同意闸门与中断门的唯一真相源。

所有工具的权限需求在此集中声明，由中间件在工具调用前统一拦截，
替代此前分散在工具内部的 `has_consented()` 内联判断。

结构约定：
- consent_required  → 要求用户已同意隐私政策（同意闸门）
- requires_approval → 需中断门人工批准后才执行
- audit_write       → 写操作是否落审计日志（阶段 3 启用）
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolPermission:
    consent_required: bool = False
    requires_approval: bool = False
    audit_write: bool = True


TOOL_PERMISSIONS: dict[str, ToolPermission] = {
    # ── 隐私同意（无闸门，任何人都能看政策/查状态/记录同意） ──
    "get_consent_policy": ToolPermission(audit_write=False),
    "consent_status": ToolPermission(audit_write=False),
    "record_consent": ToolPermission(),
    # ── 健康建档（需已同意） ──
    "get_health_profile": ToolPermission(consent_required=True),
    "save_health_profile": ToolPermission(consent_required=True),
    "save_onboarding_draft": ToolPermission(consent_required=True),
    # ── 血压记录（正常记录需同意，待确认/确认无需同意）
    #     原因：用户可能在未同意状态下回来确认上一次的异常读数 ──
    "record_blood_pressure": ToolPermission(consent_required=True),
    "get_pending_blood_pressure": ToolPermission(audit_write=False),
    "confirm_abnormal_blood_pressure": ToolPermission(requires_approval=True),
    # ── 趋势（需已同意 —— 包含健康数据） ──
    "get_seven_day_trend": ToolPermission(consent_required=True, audit_write=False),
    # ── 数据删除（中断门双保险 —— 删除会连同意记录一起清空） ──
    "delete_my_data": ToolPermission(requires_approval=True),
}


def interrupt_on() -> dict[str, bool]:
    """从权限表推导中断门配置。

    供 agent.py 中 `define_deep_agent(interrupt_on=...)` 使用，
    替代此前手工维护的硬编码 dict。
    """
    return {
        name: True
        for name, perm in TOOL_PERMISSIONS.items()
        if perm.requires_approval
    }