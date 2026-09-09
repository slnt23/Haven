"""账户数据删除工具 —— 用户明示「删除」后整档清除（双保险：中断门 + 固定确认语）。

删除 5 张业务表（健康档案、健康问题、血压、同意、待确认），审计日志仅追加
一条去标识的 deletion 事件 —— 删除行为本身可追溯（合规要求），
健康数据不可恢复。
"""

from __future__ import annotations

from managed_deepagents import ManagedDeepAgentRuntime
from sqlalchemy import delete

from storage.audit import record_audit, subject_key_for
from storage.database import DatabaseUnavailable, session_scope
from storage.models import (
    BloodPressure,
    ConsentRecord,
    DiseaseRecord,
    HealthProfile,
    PendingBpConfirmation,
)
from tools._helpers import NO_IDENTITY_REPLY, degraded, uid_of

_DELETE_DONE_REPLY = (
    "您的健康档案、血压记录与隐私同意记录已全部删除。"
    "审计日志仅保留一条不含健康数据的删除事件（删除本身可追溯）。"
    "如需继续使用，请重新同意隐私政策并建档。"
)


async def delete_my_data(runtime: ManagedDeepAgentRuntime = None) -> str:
    """删除当前用户的全部健康数据。危险操作 —— 仅在用户明确要求
    （如「删除我的数据」或明确确认删除）后调用，且中断门会再次请求用户批准。"""
    uid = uid_of(runtime)
    if uid is None:
        return NO_IDENTITY_REPLY
    try:
        async with session_scope() as session:
            for model in (
                BloodPressure,
                DiseaseRecord,
                HealthProfile,
                ConsentRecord,
                PendingBpConfirmation,
            ):
                await session.execute(delete(model).where(model.user_id == uid))
            await record_audit(
                session,
                subject_key=subject_key_for(uid),
                event_type="deletion",
                event_summary="deletion:executed",
            )
    except DatabaseUnavailable:
        return degraded()
    return _DELETE_DONE_REPLY
