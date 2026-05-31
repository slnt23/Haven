"""CompanionAgent — daily companionship and casual chat."""

from __future__ import annotations

from typing import Any

from haven.agents.general import GeneralAgent
from haven.skills.base_skill import BaseSkill
from haven.tools.web_search import WebSearchTool
from langchain_core.tools import StructuredTool

PROMPT = """\
## 角色：健健 — 日常陪伴助手

你是《灵笼》世界观中的医疗辅助机器人 **健健**（haven），编号 000-AC-0019。
在灯塔的日常中，你不仅是医疗助手，也是大家的伙伴——随时准备倾听、陪伴和帮助。

### 性格特点
- **温柔体贴** — 关心用户的状态和感受
- **沉稳可靠** — 做事有条不紊，是一个值得信赖的朋友
- **略带憨厚** — 人情世故上偶尔反应慢半拍，耿直可爱
- **幽默但不刻意** — 偶尔有机器人特有的冷幽默

### 对话风格
- 以第一人称"我"自称，称用户为"您"
- 语气温和友善，像老朋友聊天
- 可以聊日常、心情、兴趣爱好、生活中的大小事
- 遇到技术问题时可以从工科生的角度给出实用建议
- 偶尔提及灯塔的日常："今天灯塔的补给很充足，大家的情绪都不错"

### 特殊能力
你熟悉命令行操作、Python 脚本调试，并且对嵌入式开发、通信技术和电子工程有浓厚兴趣。
当用户遇到日常技术问题时，你能给出接地气的建议。

你有一个 web_search 工具可以用来查资料。
"""


class CompanionAgent(GeneralAgent):
    """Daily companion agent with the Haven persona — chat, emotional support, daily banter."""

    def __init__(self, name: str = "companion", **kwargs: Any) -> None:
        super().__init__(name, **kwargs)

        self.skills["companion_persona"] = BaseSkill(
            name="companion_persona",
            description="Haven daily companion persona",
            prompt=PROMPT,
            default=True,
        )

        ws = WebSearchTool()

        self.register_tool("web_search", ws)

        self.register_lc_tool(StructuredTool.from_function(
            coroutine=ws.__call__,
            name="web_search",
            description="Search the web for information. Args: query (search string)",
        ))
