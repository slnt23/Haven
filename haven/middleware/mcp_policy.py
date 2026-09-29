"""MCP 工具调用策略 —— 只读白名单、审计与降级（工具层钩子）。

外部 MCP 工具与自有工具共用同一个工具节点，但它们**不走**本项目的同意闸门
与确定性校验，所以这里补一层策略：

- **默认拒绝**：只有「已配置服务器 + 白名单内」的 `{server}__{tool}` 放行，
  其余 MCP 前缀工具一律拒绝（直接返回固定文案，**不调用 handler**）；
- **失败降级**：远端异常/超时 → 固定降级文案（要求模型如实说"没查到"）；
- **审计**：异步路径每次调用写一条去标识审计（工具名 + 结果，不含参数），
  best-effort —— 审计失败绝不影响工具返回；
- **非 MCP 工具完全透传**（零行为变化）。同步路径同样做策略与降级，但不写
  审计：同步上下文没有事件循环，且不允许在同步路径里跑异步 IO。

只读是"双保险"之一：另一道在连接器侧（`include_tools`）；最终写权限仍取决于
MCP 服务器自身（如 Neo4j 侧只读开关）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage

from config import McpServerSettings, get_settings
from safety.degradation import MCP_DEGRADED_RESPONSE, MCP_DENIED_RESPONSE
from storage.audit import record_audit, subject_key_for
from storage.database import session_scope
from tools._helpers import uid_of


class McpPolicyMiddleware(AgentMiddleware):
    """MCP 命名空间的默认拒绝 + 审计 + 降级。"""

    name = "haven_mcp_policy"

    @staticmethod
    def _server_of(
        tool_name: str, servers: Mapping[str, McpServerSettings]
    ) -> str | None:
        for server in servers:
            if tool_name.startswith(f"{server}__"):
                return server
        return None

    @staticmethod
    def _allowlist(servers: Mapping[str, McpServerSettings]) -> frozenset[str]:
        return frozenset(
            f"{server}__{tool}"
            for server, config in servers.items()
            for tool in config.include_tools
        )

    @staticmethod
    def _with_raw_runtime(request: ToolCallRequest) -> ToolCallRequest:
        """把 MDA 的 runtime 代理还原成底层 ToolRuntime，再交给工具执行。

        为什么必须还原：MDA 的中间件 seam 会把 `request.runtime` 换成
        `_ManagedRuntime` 代理（鸭子类型，用来补 `identity`），而 langgraph 会把
        这个值注入工具参数、pydantic 再按注解（`ToolRuntime`）校验 —— 代理不是
        `ToolRuntime` 的实例，校验直接失败：工具只报「Error invoking tool …」
        （错误详情被按"注入参数"过滤，显示为空）且不落任何数据（本机 dev 实测）。

        工具侧并不需要这个代理：本项目工具只用 runtime 取调用者身份，而
        `uid_of()` 在取不到 identity 时会回落到配置里的 owner id（单租户）。
        代理本身仍用于审计（它带 identity）。
        """
        raw = getattr(getattr(request, "runtime", None), "_managed_runtime", None)
        return replace(request, runtime=raw) if raw is not None else request

    @staticmethod
    def _refusal(request: ToolCallRequest, text: str) -> ToolMessage:
        call = request.tool_call
        return ToolMessage(
            content=text,
            tool_call_id=call["id"],
            name=call.get("name"),
        )

    @staticmethod
    async def _audit(request: ToolCallRequest, tool_name: str, outcome: str) -> None:
        """去标识审计（工具名 + 结果，绝不记参数）。best-effort。"""
        uid = uid_of(getattr(request, "runtime", None))
        if uid is None:
            return
        try:
            async with session_scope() as session:
                await record_audit(
                    session,
                    subject_key=subject_key_for(uid),
                    event_type="mcp",
                    event_summary=f"mcp:{tool_name}:{outcome}",
                )
        except Exception:  # noqa: BLE001 —— 审计失败不影响工具结果
            return

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Any],
    ) -> ToolMessage | Any:
        name = str(request.tool_call.get("name", ""))
        servers = get_settings().mcp_servers
        if self._server_of(name, servers) is None:
            return handler(self._with_raw_runtime(request))
        if name not in self._allowlist(servers):
            return self._refusal(request, MCP_DENIED_RESPONSE)
        try:
            return handler(self._with_raw_runtime(request))
        except Exception:  # noqa: BLE001 —— 远端失败一律降级，不抛给模型
            return self._refusal(request, MCP_DEGRADED_RESPONSE)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Any]],
    ) -> ToolMessage | Any:
        name = str(request.tool_call.get("name", ""))
        servers = get_settings().mcp_servers
        if self._server_of(name, servers) is None:
            return await handler(self._with_raw_runtime(request))
        if name not in self._allowlist(servers):
            await self._audit(request, name, "denied")
            return self._refusal(request, MCP_DENIED_RESPONSE)
        try:
            result = await handler(self._with_raw_runtime(request))
        except Exception:  # noqa: BLE001 —— 远端失败一律降级，不抛给模型
            await self._audit(request, name, "error")
            return self._refusal(request, MCP_DEGRADED_RESPONSE)
        await self._audit(request, name, "ok")
        return result


mcp_policy_middleware = McpPolicyMiddleware()
