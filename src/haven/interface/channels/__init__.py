"""Interface Channels —— 消息通道。"""

from haven.interface.channels.base import BaseChannel
from haven.interface.channels.feishu import FeishuChannel

__all__ = ["BaseChannel", "FeishuChannel"]
