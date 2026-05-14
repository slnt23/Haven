from __future__ import annotations

import asyncio
import email
import imaplib
import json
import logging
import re
import smtplib
from datetime import datetime, timedelta
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Callable, Optional

from forest.config import settings

logger = logging.getLogger("forest.email_service")


def _decode_header_value(value: str | bytes) -> str:
    if isinstance(value, bytes):
        decoded_parts = decode_header(value)
        result_parts: list[str] = []
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                charset = charset or "utf-8"
                result_parts.append(part.decode(charset, errors="replace"))
            else:
                result_parts.append(part)
        return "".join(result_parts)
    return value


class EmailService:
    def __init__(self, agent_handler: Optional[Callable[[str, str], Any]] = None):
        self.smtp_host = settings.email_smtp_host
        self.smtp_port = settings.email_smtp_port
        self.smtp_username = settings.email_smtp_username
        self.smtp_password = settings.email_smtp_password
        self.use_tls = settings.email_use_tls

        self.imap_host = settings.email_imap_host
        self.imap_port = settings.email_imap_port
        self.imap_username = settings.email_imap_username or settings.email_smtp_username
        self.imap_password = settings.email_imap_password or settings.email_smtp_password

        self.poll_interval = settings.email_poll_interval
        self.digest_time = settings.email_digest_time

        self.whitelist = self._parse_whitelist(settings.email_user_whitelist)
        self.agent_handler = agent_handler

        self.state_file = Path(settings.project_root) / ".data" / "email_service_state.json"
        self.processed_ids: set[str] = set()
        self._running = False
        self._tasks: list[asyncio.Task[Any]] = []

    @staticmethod
    def _parse_whitelist(raw: str) -> set[str]:
        if not raw:
            return set()
        return {addr.strip().lower() for addr in raw.split(",") if addr.strip()}

    def _load_state(self) -> None:
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text("utf-8"))
                self.processed_ids = set(data.get("processed_ids", []))
            except Exception:
                logger.warning("Failed to load email service state, starting fresh")

    def _save_state(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(
            json.dumps({"processed_ids": list(self.processed_ids)}, ensure_ascii=False),
            "utf-8",
        )

    def _send_email(self, to: str, subject: str, body: str, html: bool = False) -> bool:
        msg = MIMEMultipart()
        msg["From"] = self.smtp_username
        msg["To"] = to
        msg["Subject"] = subject
        content_type = "html" if html else "plain"
        msg.attach(MIMEText(body, content_type, "utf-8"))

        try:
            if self.use_tls:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30)
                server.starttls()
            else:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=30)
            server.login(self.smtp_username, self.smtp_password)
            server.send_message(msg)
            server.quit()
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to}: {e}")
            return False

    async def send_email(self, to: str, subject: str, body: str, html: bool = False) -> bool:
        return await asyncio.to_thread(self._send_email, to, subject, body, html)

    def _fetch_unread_emails(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        try:
            mail = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
            mail.login(self.imap_username, self.imap_password)
            mail.select("INBOX")

            status, msg_ids = mail.search(None, "UNSEEN")
            if status != "OK":
                mail.logout()
                return messages

            for msg_id in msg_ids[0].split():
                msg_id_str = msg_id.decode()
                if msg_id_str in self.processed_ids:
                    continue

                status, msg_data = mail.fetch(msg_id, "(RFC822)")
                if status != "OK":
                    continue

                raw_email = msg_data[0][1]
                parsed = email.message_from_bytes(raw_email)

                sender = _decode_header_value(parsed.get("From", ""))
                sender_addr = self._extract_email_addr(sender)
                subject = _decode_header_value(parsed.get("Subject", ""))
                date_str = parsed.get("Date", "")

                body_text = ""
                body_html = ""
                if parsed.is_multipart():
                    for part in parsed.walk():
                        content_type = part.get_content_type()
                        payload = part.get_payload(decode=True)
                        if payload is None:
                            continue
                        if content_type == "text/plain":
                            body_text += payload.decode("utf-8", errors="replace")
                        elif content_type == "text/html":
                            body_html += payload.decode("utf-8", errors="replace")
                else:
                    payload = parsed.get_payload(decode=True)
                    if payload:
                        content_type = parsed.get_content_type()
                        if content_type == "text/html":
                            body_html = payload.decode("utf-8", errors="replace")
                        else:
                            body_text = payload.decode("utf-8", errors="replace")

                messages.append({
                    "msg_id": msg_id_str,
                    "sender": sender,
                    "sender_addr": sender_addr,
                    "subject": subject,
                    "date": date_str,
                    "body_text": body_text,
                    "body_html": body_html,
                })
                self.processed_ids.add(msg_id_str)

            mail.logout()
        except Exception as e:
            logger.error(f"Failed to fetch emails: {e}")

        return messages

    @staticmethod
    def _extract_email_addr(header: str) -> str:
        match = re.search(r"<(.+?)>", header)
        if match:
            return match.group(1).lower()
        return header.strip().lower()

    async def _poll_inbox(self) -> None:
        logger.info("Email polling started")
        while self._running:
            try:
                messages = await asyncio.to_thread(self._fetch_unread_emails)
                for msg in messages:
                    sender_addr = msg["sender_addr"]
                    if self.whitelist and sender_addr not in self.whitelist:
                        logger.info(f"Ignored email from non-whitelisted sender: {sender_addr}")
                        continue

                    logger.info(f"Processing email from {sender_addr}: {msg['subject']}")
                    if self.agent_handler:
                        body = msg["body_text"] or msg["body_html"]
                        try:
                            response = self.agent_handler(msg["subject"], body)
                            if asyncio.iscoroutine(response):
                                response = await response
                            await self.send_email(
                                sender_addr,
                                f"Re: {msg['subject']}",
                                str(response),
                            )
                        except Exception as e:
                            logger.error(f"Agent handler failed: {e}")
                            await self.send_email(
                                sender_addr,
                                f"Re: {msg['subject']}",
                                f"处理您的邮件时出错: {e}",
                            )
                self._save_state()
            except Exception as e:
                logger.error(f"Poll inbox error: {e}")

            await asyncio.sleep(self.poll_interval)

    async def _send_digest(self) -> None:
        if not self.whitelist:
            return

        subject = f"Forest Agent 日报 - {datetime.now().strftime('%Y-%m-%d')}"
        body = (
            f"您好！以下是 Forest Agent 的每日汇总。\n\n"
            f"日期: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"状态: 运行正常\n"
            f"待处理消息: {len(self.processed_ids)}\n\n"
            f"---\n此邮件由 Forest Agent 自动发送。"
        )
        for user in self.whitelist:
            await self.send_email(user, subject, body)

    def _seconds_until_next_digest(self) -> float:
        now = datetime.now()
        try:
            hour, minute = map(int, self.digest_time.split(":"))
        except ValueError:
            hour, minute = 8, 0

        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return (target - now).total_seconds()

    async def _digest_scheduler(self) -> None:
        logger.info(f"Digest scheduler started, daily digest at {self.digest_time}")
        while self._running:
            delay = self._seconds_until_next_digest()
            await asyncio.sleep(delay)
            if not self._running:
                break
            try:
                await self._send_digest()
            except Exception as e:
                logger.error(f"Digest send failed: {e}")

    async def start(self) -> None:
        if self._running:
            logger.warning("EmailService is already running")
            return

        if not self.smtp_username or not self.smtp_password:
            raise RuntimeError("Email SMTP credentials not configured. Set EMAIL_SMTP_USERNAME and EMAIL_SMTP_PASSWORD.")

        self._running = True
        self._load_state()

        self._tasks = [
            asyncio.create_task(self._poll_inbox()),
            asyncio.create_task(self._digest_scheduler()),
        ]
        logger.info("EmailService started")

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        self._save_state()
        logger.info("EmailService stopped")

    async def run_forever(self) -> None:
        try:
            await self.start()
            while self._running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        finally:
            await self.stop()
