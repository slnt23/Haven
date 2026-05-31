from __future__ import annotations

import asyncio
import logging
from typing import Any

from haven.config import settings
from haven.core.base_agent import BaseAgent
from haven.services.base_channel import BaseChannel
from haven.services.email_service import EmailService

logger = logging.getLogger("haven.email_channel")


class EmailChannel(BaseChannel):
    """邮件通道——轮询 IMAP 收件箱，经 Agent 处理后通过 SMTP 回复。"""

    def __init__(self) -> None:
        super().__init__("email",
                         enabled=getattr(settings, "daemon_email_enabled", False) or False)

    async def start(self, agent: BaseAgent) -> None:
        await super().start(agent)

        if not settings.email_smtp_username or not settings.email_smtp_password:
            logger.warning("EmailChannel: SMTP credentials not configured, channel disabled")
            self.enabled = False
            return

        async def agent_handler(subject: str, body: str) -> str:
            task = f"主题: {subject}\n\n{body}"
            return await self.agent.run(task)

        self._service = EmailService(agent_handler=agent_handler)
        await self._service.start()
        logger.info("EmailChannel started")

    async def stop(self) -> None:
        if hasattr(self, "_service"):
            await self._service.stop()
        logger.info("EmailChannel stopped")
