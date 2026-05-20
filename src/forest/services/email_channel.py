from __future__ import annotations

import asyncio
import logging
from typing import Any

from forest.config import settings
from forest.core.base_agent import BaseAgent
from forest.services.base_channel import BaseChannel
from forest.services.email_service import EmailService

logger = logging.getLogger("forest.email_channel")


class EmailChannel(BaseChannel):
    """Email channel — polls IMAP inbox, processes via Agent, replies via SMTP."""

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
