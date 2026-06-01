"""core/llm.py — LLM 生命周期测试。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestBindTools:
    """bind_tools 函数测试。"""

    def test_bind_tools_with_tools(self):
        from haven.core.llm import bind_tools

        mock_llm = MagicMock()
        mock_llm.bind_tools = MagicMock(return_value="bound_llm")

        result = bind_tools(mock_llm, [MagicMock(), MagicMock()])
        assert result == "bound_llm"
        mock_llm.bind_tools.assert_called_once()

    def test_bind_tools_empty_list(self):
        from haven.core.llm import bind_tools

        mock_llm = MagicMock()
        result = bind_tools(mock_llm, [])
        assert result is mock_llm
        mock_llm.bind_tools.assert_not_called()

    def test_bind_tools_none(self):
        from haven.core.llm import bind_tools

        mock_llm = MagicMock()
        result = bind_tools(mock_llm, None)
        assert result is mock_llm


class TestCreateLLM:
    """create_llm 函数测试。"""

    def test_create_llm_deepseek(self):
        """DeepSeek provider 创建 ChatDeepSeek。"""
        with patch("haven.core.llm.get_default_model", return_value="deepseek-v4-pro"):
            with patch("haven.core.llm.get_model_config") as mock_cfg:
                mock_cfg.return_value = {
                    "provider": "deepseek",
                    "name": "deepseek-v4-pro",
                    "api_key": "test-key",
                    "base_url": "https://api.test.com",
                    "temperature": 0.5,
                    "max_tokens": 4096,
                }
                # ChatDeepSeek 在函数内部 import，需要 patch haven.core.llm 命名空间
                with patch("langchain_deepseek.ChatDeepSeek") as mock_ds:
                    mock_ds.return_value = "deepseek_llm"
                    from haven.core.llm import create_llm
                    result = create_llm()
                    assert result == "deepseek_llm"

    def test_create_llm_openai(self):
        """OpenAI provider 创建 ChatOpenAI。"""
        with patch("haven.core.llm.get_default_model", return_value="gpt-4"):
            with patch("haven.core.llm.get_model_config") as mock_cfg:
                mock_cfg.return_value = {
                    "provider": "openai",
                    "name": "gpt-4",
                    "api_key": "test-key",
                    "base_url": "https://api.openai.com",
                    "temperature": 0.7,
                    "max_tokens": 2048,
                }
                with patch("langchain_openai.ChatOpenAI") as mock_oai:
                    mock_oai.return_value = "openai_llm"
                    from haven.core.llm import create_llm
                    result = create_llm()
                    assert result == "openai_llm"

    def test_create_llm_unknown_provider_raises(self):
        """未知 provider 抛出 ValueError。"""
        with patch("haven.core.llm.get_default_model", return_value="unknown"):
            with patch("haven.core.llm.get_model_config") as mock_cfg:
                mock_cfg.return_value = {
                    "provider": "anthropic",
                    "name": "claude",
                    "api_key": "k",
                    "base_url": "url",
                    "temperature": 0.5,
                    "max_tokens": 100,
                }
                from haven.core.llm import create_llm
                with pytest.raises(ValueError, match="Unknown provider"):
                    create_llm()
