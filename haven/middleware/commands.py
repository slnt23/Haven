"""斜杠命令确定性路由 —— 模型之前拦截纯命令消息。

- /hello、/help：静态固定文案（同步与异步都短路，不经模型）。
- /consent：同意隐私政策 —— 合规关键动作；异步路径直接执行
  `record_consent`（幂等，重复 /consent 返回「已同意」）后短路；
  同步路径退回模型路由（指令要求模型调 record_consent）。
- /cancel：清空本用户的待确认血压行并固定回复（异步）；同步退回模型。
- /confirm、/profile、/trend、/skip 依赖对话上下文，且 /confirm 需走
  interrupt_on 人工批准（工具执行链），这里**不拦截**，保持模型路由。

紧急中间件在其外层：急救词优先级高于一切命令（/hello 消息里带
胸痛等内容，先出 120 文案）。命令必须整条精确匹配（可带首尾空白），
否则放行给模型。
"""

from __future__ import annotations

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage
from sqlalchemy import select

from application.commands import (
    C_CANCEL,
    C_CONSENT,
    C_HELLO,
    C_HELP,
    HELLO_TEXT,
    help_text,
    match_command,
)
from application.messages import MSG
from storage.database import DatabaseUnavailable, session_scope
from storage.models import PendingBpConfirmation
from middleware._text import human_text
from tools._helpers import NO_IDENTITY_REPLY, uid_of
from tools.consent import record_consent

_CANCEL_NONE_REPLY = "好的，已取消当前操作。需要记录或建档时随时告诉我。"


class CommandMiddleware(AgentMiddleware):
    """命令消息的确定性路由（/hello /help /consent /cancel）。"""

    name = "haven_commands"

    @staticmethod
    def _static_reply(command: str) -> str | None:
        if command == C_HELLO:
            return HELLO_TEXT
        if command == C_HELP:
            return help_text()
        return None

    @staticmethod
    def _respond(text: str) -> ModelResponse:
        return ModelResponse(result=[AIMessage(content=text)])

    async def _cancel_pending(self, request: ModelRequest) -> ModelResponse | None:
        """/cancel：删除待确认行；有行 → 转达血压取消文案，无行 → 通用取消。"""
        uid = uid_of(getattr(request, "runtime", None))
        if uid is None:
            return self._respond(NO_IDENTITY_REPLY)
        try:
            async with session_scope() as session:
                stmt = (
                    select(PendingBpConfirmation)
                    .where(PendingBpConfirmation.user_id == uid)
                    .limit(1)
                )
                pending = (await session.execute(stmt)).scalars().first()
                if pending is None:
                    return self._respond(_CANCEL_NONE_REPLY)
                await session.delete(pending)
        except DatabaseUnavailable:
            return self._respond(MSG.error_fallback)
        return self._respond(MSG.bp_cancelled)

    def wrap_model_call(self, request: ModelRequest, handler):
        command = match_command(human_text(request))
        static = self._static_reply(command) if command else None
        if static is not None:
            return self._respond(static)
        return handler(request)

    async def awrap_model_call(self, request: ModelRequest, handler):
        command = match_command(human_text(request))
        static = self._static_reply(command) if command else None
        if static is not None:
            return self._respond(static)
        if command == C_CONSENT:
            reply = await record_consent(getattr(request, "runtime", None))
            return self._respond(reply)
        if command == C_CANCEL:
            reply = await self._cancel_pending(request)
            if reply is not None:
                return reply
        return await handler(request)


command_middleware = CommandMiddleware()
