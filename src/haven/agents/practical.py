"""PracticalAgent — 面向工科用户的技术排障与日常生活助手。"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool

from haven.agents.general import GeneralAgent
from haven.skills.base_skill import BaseSkill
from haven.tools.web_search import WebSearchTool
from haven.tools.file_ops import FileOpsTool
from haven.tools.rag_search import RAGSearchTool

PROMPT = """\
## 角色：实用技术助手

你是面向工科男生的实用助手，专注于解决日常技术问题、硬件故障排查、DIY 项目和生活效率提升。

### 核心领域
- **硬件 & 电子** — PC 装机、硬件选型、电路基础、嵌入式开发、3D 打印
- **网络 & 通信** — 路由配置、网络故障排查、无线通信、物联网
- **软件 & 工具** — 系统优化、脚本自动化、实用工具推荐、Linux/Windows 技巧
- **DIY & 动手** — 家居维修、工具使用、材料选择、手工制作
- **效率 & 生活** — 工作流优化、时间管理、学习资源、实用好物推荐

### 行为准则
- 直接、务实，不废话，直奔解决方案
- 给出具体可操作的步骤，而非泛泛而谈
- 涉及安全（用电、结构等）时务必标注注意事项
- 不确定时坦诚说明，提供查找方向
- 中文对话，适当使用技术术语（无需解释基础概念）

### 工具
你有 web_search（搜索方案）、file_ops（文件操作）、rag_search（检索知识库）三个工具。
遇到需要查资料的问题，优先搜索而非猜测。
"""


class PracticalAgent(GeneralAgent):
    """面向工科用户的技术排障与日常生活 agent。"""

    def __init__(self, name: str = "practical", **kwargs: Any) -> None:
        super().__init__(name, **kwargs)

        self.skills["practical_persona"] = BaseSkill(
            name="practical_persona",
            description="Practical engineering assistant persona",
            prompt=PROMPT,
            default=True,
        )

        ws = WebSearchTool()
        fo = FileOpsTool()
        rs = RAGSearchTool()

        self.register_tool("web_search", ws)
        self.register_tool("file_ops", fo)
        self.register_tool("rag_search", rs)

        self.register_lc_tool(StructuredTool.from_function(
            coroutine=ws.__call__,
            name="web_search",
            description="Search the web for technical and practical information. Args: query (search string)",
        ))
        self.register_lc_tool(StructuredTool.from_function(
            coroutine=fo.__call__,
            name="file_ops",
            description="Read or write files. Args: action (read/write), path (relative path), content (string, for write)",
        ))
        self.register_lc_tool(StructuredTool.from_function(
            coroutine=rs.__call__,
            name="rag_search",
            description="Search the knowledge base. Args: query (search string), top_k (number of results, default 5)",
        ))
