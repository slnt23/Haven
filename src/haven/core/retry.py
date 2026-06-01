"""LLM 调用重试 — exponential backoff + jitter。

可重试错误:
  - 网络错误 (ConnectionError, TimeoutError, OSError)
  - Rate Limit (429 / rate limit / too many requests)
  - 临时服务不可用 (5xx / server error / service unavailable)

用法::

    from haven.core.retry import retry_async

    response = await retry_async(
        llm.ainvoke,
        messages,
        max_retries=3,
        base_delay=1.0,
    )
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Awaitable, Callable, TypeVar

logger = logging.getLogger("haven.retry")

T = TypeVar("T")

_RETRYABLE_MESSAGES: list[str] = [
    "rate limit",
    "rate limited",
    "too many requests",
    "429",
    "server error",
    "service unavailable",
    "internal server error",
    "bad gateway",
    "gateway timeout",
    "503",
    "502",
    "504",
    "overloaded",
    "capacity",
    "throttl",
]

_RETRYABLE_TYPES: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)


def _is_retryable(exc: BaseException) -> bool:
    """判断异常是否可重试。"""
    if isinstance(exc, _RETRYABLE_TYPES):
        return True

    msg = str(exc).lower()
    for pattern in _RETRYABLE_MESSAGES:
        if pattern in msg:
            return True

    # httpx.HTTPStatusError → 检查 5xx
    if hasattr(exc, "response"):
        resp = getattr(exc, "response", None)
        if resp is not None:
            status = getattr(resp, "status_code", 0)
            if 500 <= status < 600 or status == 429:
                return True

    # openai / langchain 的嵌套异常
    cause = getattr(exc, "__cause__", None)
    if cause is not None and cause is not exc:
        return _is_retryable(cause)

    return False


def _backoff(attempt: int, base_delay: float = 1.0) -> float:
    """指数退避 + 随机抖动。"""
    delay = base_delay * (2 ** (attempt - 1))
    jitter = delay * 0.3 * random.random()
    return delay + jitter


async def retry_async(
    fn: Callable[..., Awaitable[T]],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 1.0,
    **kwargs: Any,
) -> T:
    """异步调用 *fn*，失败时按指数退避重试。

    Args:
        fn: 异步可调用对象。
        *args: 传递给 *fn* 的位置参数。
        max_retries: 最大重试次数（含首次调用共 max_retries+1 次）。
        base_delay: 基础延迟秒数。
        **kwargs: 传递给 *fn* 的关键字参数。

    Returns:
        *fn* 的返回值。

    Raises:
        原始异常 — 超过最大重试次数后重新抛出最后一次异常。
    """
    last_exc: BaseException | None = None
    total_attempts = max_retries + 1

    for attempt in range(1, total_attempts + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if not _is_retryable(exc):
                raise

            if attempt >= total_attempts:
                logger.warning(
                    "LLM call failed after %d attempt(s): retry_count=%d error_type=%s",
                    attempt,
                    max_retries,
                    type(exc).__name__,
                )
                raise

            wait = _backoff(attempt, base_delay)
            logger.warning(
                "LLM call attempt %d/%d failed: error_type=%s retry_count=%d wait_seconds=%.2f",
                attempt,
                total_attempts,
                type(exc).__name__,
                attempt,
                wait,
            )
            await asyncio.sleep(wait)

    # 理论上不会到这里，但类型检查需要
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("retry_async: unreachable")
