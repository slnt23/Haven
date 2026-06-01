"""retry_async — LLM 调用重试测试。"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def retry_async():
    from haven.core.retry import retry_async

    return retry_async


class TestRetryAsync:
    """retry_async 核心功能测试。"""

    @pytest.mark.asyncio
    async def test_success_first_try(self, retry_async):
        """首次成功不重试。"""
        mock_fn = AsyncMock(return_value="ok")
        result = await retry_async(mock_fn, "arg1", kw=1)
        assert result == "ok"
        mock_fn.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retry_once_then_success(self, retry_async):
        """一次失败后重试成功。"""
        call_count = [0]

        async def flaky():
            call_count[0] += 1
            if call_count[0] == 1:
                raise ConnectionError("网络不可达")
            return "recovered"

        result = await retry_async(flaky, max_retries=3, base_delay=0.01)
        assert result == "recovered"
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_retry_twice_then_success(self, retry_async):
        """两次失败后重试成功。"""
        call_count = [0]

        async def flaky():
            call_count[0] += 1
            if call_count[0] <= 2:
                raise TimeoutError("超时")
            return "finally ok"

        result = await retry_async(flaky, max_retries=3, base_delay=0.01)
        assert result == "finally ok"
        assert call_count[0] == 3

    @pytest.mark.asyncio
    async def test_exceed_max_retries_raises(self, retry_async):
        """超过最大重试次数后抛出原始异常。"""
        original = ConnectionError("永远连不上")

        async def always_fails():
            raise original

        with pytest.raises(ConnectionError) as exc_info:
            await retry_async(always_fails, max_retries=2, base_delay=0.01)

        assert exc_info.value is original
        # 首次 + 2 次重试 = 共 3 次调用
        assert "永远连不上" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_non_retryable_raises_immediately(self, retry_async):
        """不可重试异常直接抛出，不等待。"""
        call_count = [0]

        async def type_error():
            call_count[0] += 1
            raise TypeError("类型不匹配")

        with pytest.raises(TypeError):
            await retry_async(type_error, max_retries=3, base_delay=0.01)

        assert call_count[0] == 1  # 不应重试

    @pytest.mark.asyncio
    async def test_rate_limit_is_retryable(self, retry_async):
        """Rate Limit 错误可重试。"""
        call_count = [0]

        async def rate_limited():
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("rate limit exceeded, try again in 30s")
            return "ok"

        result = await retry_async(rate_limited, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_server_error_5xx_is_retryable(self, retry_async):
        """503 服务不可用可重试。"""
        call_count = [0]

        async def server_error():
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("503 service unavailable")
            return "ok"

        result = await retry_async(server_error, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_httpx_status_error_5xx_retryable(self, retry_async):
        """httpx 5xx 响应可重试。"""
        call_count = [0]

        class FakeResponse:
            status_code = 502

        class HTTPError(Exception):
            def __init__(self):
                self.response = FakeResponse()

        async def httpx_error():
            call_count[0] += 1
            if call_count[0] == 1:
                raise HTTPError()
            return "ok"

        result = await retry_async(httpx_error, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_httpx_status_429_retryable(self, retry_async):
        """httpx 429 可重试。"""
        call_count = [0]

        class FakeResponse:
            status_code = 429

        class HTTPError(Exception):
            def __init__(self):
                self.response = FakeResponse()

        async def httpx_429():
            call_count[0] += 1
            if call_count[0] == 1:
                raise HTTPError()
            return "ok"

        result = await retry_async(httpx_429, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_nested_cause_is_retryable(self, retry_async):
        """嵌套异常链中的可重试错误被检测。"""
        call_count = [0]

        async def nested_error():
            call_count[0] += 1
            if call_count[0] == 1:
                inner = ConnectionError("连接被拒绝")
                raise RuntimeError("wrapper") from inner
            return "ok"

        result = await retry_async(nested_error, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert call_count[0] == 2


class TestBackoff:
    """退避算法测试。"""

    def test_backoff_exponential(self):
        from haven.core.retry import _backoff

        d1 = _backoff(1, base_delay=1.0)
        d2 = _backoff(2, base_delay=1.0)
        d3 = _backoff(3, base_delay=1.0)

        # 指数增长: 1×2^0=1, 1×2^1=2, 1×2^2=4 (plus jitter)
        assert d1 < d2 < d3

    def test_backoff_custom_base(self):
        from haven.core.retry import _backoff

        d1 = _backoff(1, base_delay=0.5)
        d2 = _backoff(2, base_delay=0.5)

        # 0.5×2^0=0.5, 0.5×2^1=1.0
        assert d1 < d2

    def test_backoff_jitter_range(self):
        from haven.core.retry import _backoff

        for _ in range(100):
            d = _backoff(2, base_delay=1.0)
            # base=2, jitter max=2*0.3=0.6 → range [2, 2.6]
            assert 2.0 <= d <= 2.6


class TestIsRetryable:
    """_is_retryable 函数测试。"""

    def test_connection_error(self):
        from haven.core.retry import _is_retryable

        assert _is_retryable(ConnectionError("连接超时")) is True

    def test_timeout_error(self):
        from haven.core.retry import _is_retryable

        assert _is_retryable(TimeoutError()) is True

    def test_os_error(self):
        from haven.core.retry import _is_retryable

        assert _is_retryable(OSError("Network unreachable")) is True

    def test_rate_limit_message(self):
        from haven.core.retry import _is_retryable

        assert _is_retryable(RuntimeError("rate limit exceeded")) is True

    def test_429_message(self):
        from haven.core.retry import _is_retryable

        assert _is_retryable(RuntimeError("HTTP 429 Too Many Requests")) is True

    def test_503_message(self):
        from haven.core.retry import _is_retryable

        assert _is_retryable(RuntimeError("503 Service Unavailable")) is True

    def test_type_error_not_retryable(self):
        from haven.core.retry import _is_retryable

        assert _is_retryable(TypeError("类型错误")) is False

    def test_value_error_not_retryable(self):
        from haven.core.retry import _is_retryable

        assert _is_retryable(ValueError("参数无效")) is False

    def test_overloaded_message(self):
        from haven.core.retry import _is_retryable

        assert _is_retryable(RuntimeError("server overloaded")) is True

    def test_throttled_message(self):
        from haven.core.retry import _is_retryable

        assert _is_retryable(RuntimeError("request throttled")) is True


class TestRetryLogging:
    """日志记录测试。"""

    @pytest.mark.asyncio
    async def test_logs_retry_attempts(self, retry_async, caplog):
        """重试时记录 retry_count、error_type、wait_seconds。"""
        call_count = [0]

        async def flaky():
            call_count[0] += 1
            if call_count[0] <= 2:
                raise ConnectionError("network down")
            return "ok"

        with caplog.at_level(logging.WARNING, logger="haven.retry"):
            result = await retry_async(flaky, max_retries=3, base_delay=0.01)

        assert result == "ok"

        retry_logs = [r for r in caplog.records if "attempt" in r.message]
        assert len(retry_logs) == 2
        assert "error_type" in retry_logs[0].message
        assert "ConnectionError" in retry_logs[0].message
        assert "wait_seconds" in retry_logs[0].message

    @pytest.mark.asyncio
    async def test_logs_final_failure(self, retry_async, caplog):
        """最终失败时记录完整信息。"""

        async def always_fails():
            raise ConnectionError("永久故障")

        with caplog.at_level(logging.WARNING, logger="haven.retry"):
            with pytest.raises(ConnectionError):
                await retry_async(always_fails, max_retries=2, base_delay=0.01)

        final_logs = [r for r in caplog.records if "failed after" in r.message]
        assert len(final_logs) == 1
        assert "retry_count=2" in final_logs[0].message
        assert "error_type" in final_logs[0].message

    @pytest.mark.asyncio
    async def test_no_log_on_immediate_success(self, retry_async, caplog):
        """首次成功不产生日志。"""

        async def works():
            return "ok"

        with caplog.at_level(logging.WARNING, logger="haven.retry"):
            await retry_async(works, max_retries=3, base_delay=0.01)

        retry_logs = [r for r in caplog.records if "attempt" in r.message]
        assert len(retry_logs) == 0


class TestRetryAsyncWithRuntime:
    """retry_async + AgentRuntime 集成测试。"""

    @pytest.mark.asyncio
    async def test_runtime_direct_with_retry(self, runtime_with_mock_llm):
        """Runtime._invoke_direct 使用 retry_async 包装。"""
        rt = runtime_with_mock_llm
        rt._active_tools = []

        call_count = [0]

        async def _flaky_ainvoke(messages, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ConnectionError("transient network error")
            from langchain_core.messages import AIMessage

            return AIMessage(content="retry success")

        rt.llm.ainvoke = AsyncMock(side_effect=_flaky_ainvoke)

        result = await rt.run("test", use_memory=False)
        assert result == "retry success"
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_runtime_tool_loop_with_retry(self, runtime_with_mock_llm):
        """Runtime._invoke_with_tool_loop 中 LLM 调用受重试保护。"""
        rt = runtime_with_mock_llm

        call_count = [0]

        async def _flaky_ainvoke(messages, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise TimeoutError("LLM timeout")
            from langchain_core.messages import AIMessage

            return AIMessage(content="final answer")

        rt.llm.ainvoke = AsyncMock(side_effect=_flaky_ainvoke)

        result = await rt.run("test", use_memory=False)
        assert result == "final answer"
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_runtime_propagates_final_error(self, runtime_with_mock_llm):
        """最终失败保留原异常。"""
        rt = runtime_with_mock_llm
        rt._active_tools = []

        original = ConnectionError("persistent failure")
        rt.llm.ainvoke = AsyncMock(side_effect=original)

        with pytest.raises(ConnectionError) as exc_info:
            await rt.run("test", use_memory=False)

        assert exc_info.value is original
