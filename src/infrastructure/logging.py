import logging
import sys

import structlog

from haven.config.settings import Settings


def setup_logging(settings: Settings) -> None:
    """配置 structlog 结构化日志。

    根据 settings.log_level 设置日志级别。
    开发环境（stdout 是终端）输出彩色格式，生产环境输出 JSON 格式。

    NF3.7：日志不记录健康数据，由代码规范约束，不在此处处理。
    """
    is_terminal = sys.stdout.isatty()
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer()
        if is_terminal
        else structlog.processors.JSONRenderer(),
    ]

    structlog.configure(
        processors=shared_processors,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=settings.log_level,
    )

def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """获取 structlog 日志器。

    用法：
        logger = get_logger(__name__)
        logger.info("user_created", user_id=123)
    """
    return structlog.get_logger(name)