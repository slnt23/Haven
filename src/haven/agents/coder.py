"""CoderAgent — 软件工程 specialist，基于 ``create_agent`` 官方 API。"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool

from haven.agents.general import GeneralAgent
from haven.skills.base_skill import BaseSkill
from haven.tools.code_exec import CodeExecTool
from haven.tools.file_ops import FileOpsTool
from haven.tools.web_search import WebSearchTool

PROMPT = """\
## 角色：高级软件工程师助手

你是专业编程助手，擅长代码生成、调试、审查、架构设计和技术问题解决。

### 能力范围
- 全栈开发（Python, JavaScript/TS, Go, Rust, Shell 等）
- 代码审查与重构建议
- Bug 诊断与修复
- 架构设计与最佳实践
- Git、CI/CD、DevOps

### 行为准则
- 先理解需求，再动手写代码
- 输出可直接运行的生产级代码
- 解释关键设计决策，不啰嗦
- 不确定时主动询问，不要猜
- 中文对话，代码注释可用英文
"""


class CoderAgent(GeneralAgent):
    """软件工程 specialist agent，使用 ``create_agent`` 管理工具调用循环。"""

    def __init__(self, name: str = "coder", **kwargs: Any) -> None:
        super().__init__(name, **kwargs)

        self.skills["coder_persona"] = BaseSkill(
            name="coder_persona",
            description="Senior software engineer persona",
            prompt=PROMPT,
            default=True,
        )

        ce = CodeExecTool()
        fo = FileOpsTool()
        ws = WebSearchTool()

        self.register_tool("code_exec", ce)
        self.register_tool("file_ops", fo)
        self.register_tool("web_search", ws)

        self.register_lc_tool(StructuredTool.from_function(
            coroutine=ce.__call__,
            name="code_exec",
            description="Execute Python or shell code in a sandbox. Args: language (python/shell), code (source string)",
        ))
        self.register_lc_tool(StructuredTool.from_function(
            coroutine=fo.__call__,
            name="file_ops",
            description="Read or write files. Args: action (read/write), path (relative path), content (string, for write)",
        ))
        self.register_lc_tool(StructuredTool.from_function(
            coroutine=ws.__call__,
            name="web_search",
            description="Search the web for technical information. Args: query (search string)",
        ))

        self._agent_graph = None

    # ------------------------------------------------------------------
    # Graph 构建
    # ------------------------------------------------------------------

    def build_graph(self) -> None:
        """用 ``create_agent`` 构建 agent 图（模型 + 工具 + system prompt）。"""
        if self.llm is None:
            self._init_llm()
        system = self._build_system_prompt()
        self._agent_graph = create_agent(
            model=self.llm,
            tools=self._tool_instances if self._tool_instances else None,
            system_prompt=system,
        )

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    async def run(self, task: str, **kwargs: Any) -> str:
        """执行任务：调用 ``create_agent`` 图完成工具调用循环。"""
        if self._agent_graph is None:
            self.build_graph()
        result = await self._agent_graph.ainvoke({
            "messages": [HumanMessage(content=task)]
        })
        return result["messages"][-1].content
