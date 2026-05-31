import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from haven.config import settings
from haven.tools.tool_registry import ToolRegistry


@ToolRegistry.register("email_sender")
class EmailSenderTool:
    def __init__(self):
        self.smtp_host = settings.email_smtp_host
        self.smtp_port = settings.email_smtp_port
        self.username = settings.email_smtp_username
        self.password = settings.email_smtp_password
        self.use_tls = settings.email_use_tls

    def send(self, to: str, subject: str, body: str, html: bool = False) -> bool:
        msg = MIMEMultipart()
        msg["From"] = self.username
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

            server.login(self.username, self.password)
            server.send_message(msg)
            server.quit()
            return True
        except Exception:
            return False

    async def __call__(self, to: str, subject: str, body: str) -> str:
        success = self.send(to, subject, body)
        if success:
            return f"邮件已成功发送至 {to}"
        return f"邮件发送至 {to} 失败"
