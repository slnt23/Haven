from __future__ import annotations

import asyncio
import json
import logging
import threading

from haven.config import settings
from haven.core.base_agent import BaseAgent
from haven.core.session import ChatSession
from haven.services.base_channel import BaseChannel

logger = logging.getLogger("haven.feishu_channel")


# ------------------------------------------------------------------
# asynchronous reply helper — offloads the synchronous lark API call
# to a worker thread so the main event loop isn't blocked
# ------------------------------------------------------------------

async def _send_reply(
    app_id: str, app_secret: str, open_id: str, text: str,
) -> None:
    """Send a text reply via Feishu :ref:`CreateMessage` API in a thread."""

    def _sync() -> None:
        from lark_oapi.api.im.v1 import (
            CreateMessageRequest, CreateMessageRequestBody,
        )

        body = CreateMessageRequestBody.builder() \
            .receive_id(open_id) \
            .msg_type("text") \
            .content(json.dumps({"text": text}, ensure_ascii=False)) \
            .build()

        req = CreateMessageRequest.builder() \
            .receive_id_type("open_id") \
            .request_body(body) \
            .build()

        from lark_oapi import Client
        client = Client.builder() \
            .app_id(app_id) \
            .app_secret(app_secret) \
            .build()

        resp = client.im.v1.message.create(req)
        if not resp.success():
            logger.error("FeishuChannel: reply failed: %s", resp.msg)

    await asyncio.to_thread(_sync)


# ------------------------------------------------------------------
# FeishuChannel
# ------------------------------------------------------------------

class FeishuChannel(BaseChannel):
    """Feishu / Lark messaging channel.

    Receives messages via WebSocket long-connection and replies through
    the Feishu Open API.  No public URL or webhook endpoint is required.

    **Prerequisites** — Create a Feishu enterprise app in the developer
    console, enable Bot capability, and obtain App ID + App Secret.
    """

    def __init__(self, app_id: str = "", app_secret: str = "") -> None:
        super().__init__(
            "feishu",
            enabled=getattr(settings, "daemon_feishu_enabled", False),
        )
        self.app_id = app_id or getattr(settings, "daemon_feishu_app_id", "")
        self.app_secret = app_secret or getattr(settings, "daemon_feishu_app_secret", "")
        self._session: ChatSession | None = None
        self._running = False
        self._ws_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # channel life-cycle
    # ------------------------------------------------------------------

    async def start(self, agent: BaseAgent) -> None:
        await super().start(agent)

        if not self.app_id or not self.app_secret:
            logger.warning(
                "FeishuChannel: app_id/app_secret not configured, channel disabled"
            )
            self.enabled = False
            return

        self._session = ChatSession(agent)

        loop = asyncio.get_running_loop()

        # The lark-oapi WebSocket Client.start() is synchronous and blocking
        # (it calls ``run_until_complete`` internally).  Run it in a daemon
        # thread so the daemon's asyncio loop is not blocked.
        self._running = True
        self._ws_thread = threading.Thread(
            target=self._run_ws, args=(loop,), daemon=True,
        )
        self._ws_thread.start()
        logger.info("FeishuChannel started (app_id=%s…)", self.app_id[:8])

    async def stop(self) -> None:
        self._running = False
        # The WS thread is a daemon — it will be terminated when the process
        # exits.  There is no public stop() on lark-oapi's WS Client.
        logger.info("FeishuChannel stopped")

    @property
    def status_detail(self) -> str:
        if self.app_id:
            return f"app_id={self.app_id[:8]}…"
        return "not configured"

    # ------------------------------------------------------------------
    # WebSocket event handler (runs in worker thread)
    # ------------------------------------------------------------------

    def _run_ws(self, main_loop: asyncio.AbstractEventLoop) -> None:
        """Blocking entry-point for the WebSocket worker thread."""

        # Build a dispatcher that forwards ``im.message.receive_v1`` events
        # to the main asyncio loop.
        from lark_oapi.event.dispatcher_handler import EventDispatcherHandler

        def _on_message(event) -> None:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._handle_event(event), main_loop,
                )
            except Exception:
                logger.exception("FeishuChannel: event dispatch failed")

        handler = (EventDispatcherHandler
                   .builder("", "")
                   .register_p2_im_message_receive_v1(_on_message)
                   .build())

        from lark_oapi.ws import Client as WsClient

        client = WsClient(
            app_id=self.app_id,
            app_secret=self.app_secret,
            event_handler=handler,
            auto_reconnect=True,
        )

        try:
            client.start()
        except Exception:
            if self._running:
                logger.exception("FeishuChannel: WS client crashed")

    # ------------------------------------------------------------------
    # event processing (runs on main asyncio loop)
    # ------------------------------------------------------------------

    async def _handle_event(self, event) -> None:
        """Process a single incoming message event from Feishu."""

        evt = event.event
        if evt is None:
            return

        message = evt.message
        if message is None or message.message_type != "text":
            return

        # Parse the text content (Feishu delivers it as a JSON string)
        text = ""
        try:
            content = json.loads(message.content or "{}")
            text = content.get("text", "").strip()
        except json.JSONDecodeError:
            return

        if not text:
            return

        # If the message contains @mentions, strip the leading @bot_name
        if message.mentions:
            for mention in message.mentions:
                key = getattr(mention, "key", "")
                if key:
                    text = text.replace(key, "").strip()

        open_id = getattr(evt.sender.sender_id if evt.sender else None, "open_id", "") or ""
        chat_id = message.chat_id or ""

        logger.info(
            "FeishuChannel: message open_id=%s chat=%s: %s",
            open_id, chat_id, text[:100],
        )

        # Stamp the agent memory with per-user identity
        self.agent.memory.session_id = f"feishu_{open_id}"
        self.agent.memory.entity_name = f"feishu_{open_id}"
        self.agent.memory.channel = "feishu"

        # Process through ChatSession
        try:
            response = await self._session.process(text)
        except Exception:
            logger.exception("FeishuChannel: agent error")
            response = "抱歉，处理消息时出错了，请稍后重试。"

        # Feishu text messages have a ~20 KB payload limit.  Truncate if
        # the agent's response exceeds it (reserve some margin).
        max_len = 18000
        if len(response) > max_len:
            response = response[:max_len] + "\n\n…(内容过长已截断)"

        if open_id:
            await _send_reply(self.app_id, self.app_secret, open_id, response)

        # Background fact extraction
        asyncio.create_task(self.agent.extract_facts_async())
