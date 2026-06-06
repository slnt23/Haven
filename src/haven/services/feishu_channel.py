from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any

from haven.config import settings
from haven.services.base_channel import BaseChannel

logger = logging.getLogger("haven.feishu_channel")


# ------------------------------------------------------------------
# 异步回复辅助函数——将同步 lark API 调用放到工作线程，
# 避免阻塞主事件循环
# ------------------------------------------------------------------


async def _send_reply(
    app_id: str,
    app_secret: str,
    open_id: str,
    text: str,
) -> None:
    """在线程中通过飞书 CreateMessage API 发送文本回复。"""

    def _sync() -> None:
        from lark_oapi.api.im.v1 import (
            CreateMessageRequest,
            CreateMessageRequestBody,
        )

        body = (
            CreateMessageRequestBody.builder()
            .receive_id(open_id)
            .msg_type("text")
            .content(json.dumps({"text": text}, ensure_ascii=False))
            .build()
        )

        req = CreateMessageRequest.builder().receive_id_type("open_id").request_body(body).build()

        from lark_oapi import Client

        client = Client.builder().app_id(app_id).app_secret(app_secret).build()

        resp = client.im.v1.message.create(req)
        if not resp.success():
            logger.error("FeishuChannel: reply failed: %s", resp.msg)

    await asyncio.to_thread(_sync)


# ------------------------------------------------------------------
# FeishuChannel
# ------------------------------------------------------------------


class FeishuChannel(BaseChannel):
    """飞书 / Lark 消息通道。

    通过 WebSocket 长连接接收消息，经飞书 Open API 回复。
    无需公网 URL 或 webhook 端点。

    **前置条件**——在飞书开发者控制台创建企业应用，启用 Bot 能力，获取 App ID 和 App Secret。
    """

    def __init__(self, app_id: str = "", app_secret: str = "") -> None:
        super().__init__(
            "feishu",
            enabled=getattr(settings, "daemon_feishu_enabled", False),
        )
        self.app_id = app_id or getattr(settings, "daemon_feishu_app_id", "")
        self.app_secret = app_secret or getattr(settings, "daemon_feishu_app_secret", "")
        self._session: Any = None
        self._running = False
        self._ws_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # 通道生命周期
    # ------------------------------------------------------------------

    async def start(self, agent: Any) -> None:
        await super().start(agent)

        if not self.app_id or not self.app_secret:
            logger.warning("FeishuChannel: app_id/app_secret not configured, channel disabled")
            self.enabled = False
            return

        self._session = agent  # Coordinator 实例，直接调用 execute()

        loop = asyncio.get_running_loop()

        # lark-oapi 的 WebSocket Client.start() 是同步阻塞的
        # （内部调用 ``run_until_complete``）。放到守护线程中运行，
        # 避免阻塞守护进程的 asyncio 循环。
        self._running = True
        self._ws_thread = threading.Thread(
            target=self._run_ws,
            args=(loop,),
            daemon=True,
        )
        self._ws_thread.start()
        logger.info("FeishuChannel started (app_id=%s…)", self.app_id[:8])

    async def stop(self) -> None:
        self._running = False
        # WS 线程是守护线程——进程退出时自动终止。
        # lark-oapi 的 WS Client 不提供公开的 stop() 方法。
        logger.info("FeishuChannel stopped")

    @property
    def status_detail(self) -> str:
        if self.app_id:
            return f"app_id={self.app_id[:8]}…"
        return "not configured"

    # ------------------------------------------------------------------
    # WebSocket 事件处理（在工作线程中运行）
    # ------------------------------------------------------------------

    def _run_ws(self, main_loop: asyncio.AbstractEventLoop) -> None:
        """WebSocket 工作线程的阻塞入口。"""

        # 构建分发器，将 ``im.message.receive_v1`` 事件转发到主 asyncio 循环。
        from lark_oapi.event.dispatcher_handler import EventDispatcherHandler

        def _on_message(event) -> None:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._handle_event(event),
                    main_loop,
                )
            except Exception:
                logger.exception("FeishuChannel: event dispatch failed")

        handler = (
            EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(_on_message)
            .build()
        )

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
    # 事件处理（在主 asyncio 循环中运行）
    # ------------------------------------------------------------------

    async def _handle_event(self, event) -> None:
        """处理来自飞书的单条消息事件。"""

        evt = event.event
        if evt is None:
            return

        message = evt.message
        if message is None or message.message_type != "text":
            return

        # 解析文本内容（飞书以 JSON 字符串形式传递）
        text = ""
        try:
            content = json.loads(message.content or "{}")
            text = content.get("text", "").strip()
        except json.JSONDecodeError:
            return

        if not text:
            return

        # 若消息包含 @提及，去除前导的 @bot_name
        if message.mentions:
            for mention in message.mentions:
                key = getattr(mention, "key", "")
                if key:
                    text = text.replace(key, "").strip()

        open_id = getattr(evt.sender.sender_id if evt.sender else None, "open_id", "") or ""
        chat_id = message.chat_id or ""

        logger.info(
            "FeishuChannel: message open_id=%s chat=%s: %s",
            open_id,
            chat_id,
            text[:100],
        )

        # 按用户身份隔离会话状态
        self.agent.state.session_id = f"feishu_{open_id}"
        self.agent.state.entity_name = f"feishu_{open_id}"
        self.agent.state.channel = "feishu"

        # 通过 Coordinator 处理
        try:
            response = await self._session.execute(text)
        except Exception:
            logger.exception("FeishuChannel: agent error")
            response = "抱歉，处理消息时出错了，请稍后重试。"

        # 飞书文本消息有约 20KB 的载荷限制。若 agent 响应超限则截断（预留余量）。
        max_len = 18000
        if len(response) > max_len:
            response = response[:max_len] + "\n\n…(内容过长已截断)"

        if open_id:
            await _send_reply(self.app_id, self.app_secret, open_id, response)

        # checkpointer 自动持久化
