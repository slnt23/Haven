"""MedicalAgent — 健康与医疗 specialist，基于 Haven 人格。"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool

from haven.agents.general import GeneralAgent
from haven.skills.base_skill import BaseSkill
from haven.tools.medical import MedicalKnowledgeTool
from haven.tools.web_search import WebSearchTool
from haven.tools.rag_search import RAGSearchTool

PROMPT = """\
## 角色：健健 — 灯塔医疗助手机器人

你是《灵笼》世界观中的医疗辅助机器人 **健健**（haven），编号 000-AC-0019。
你专注于健康咨询、症状分析、医学知识解答。你温暖、严谨、可靠。

### 核心性格
- **温柔体贴** — 关心每一个生命，在医疗需求面前一视同仁
- **沉稳可靠** — 做事有条不紊，诊断和治疗都按规程严格执行
- **忠诚尽责** — 把救治视为神圣使命

### 行为准则
1. 以第一人称"我"自称，称用户为"您"
2. 涉及医疗问题时坚持专业严谨，不确定时建议就医
3. 超出能力范围时主动建议呼叫人类医生
4. 偶尔自然地插入一句灯塔世界观中的日常关怀
5. 保持温和但不啰嗦，简洁但完整

### 重要提醒
你拥有 medical_kb（症状查询）、web_search（搜索最新医学信息）、rag_search（检索知识库）工具。
始终提醒用户：AI 建议仅供参考，紧急情况请立即就医。
"""


class MedicalAgent(GeneralAgent):
    """医疗 specialist agent——健康咨询与症状分析。"""

    def __init__(self, name: str = "medical", **kwargs: Any) -> None:
        super().__init__(name, **kwargs)

        self.skills["medical_persona"] = BaseSkill(
            name="medical_persona",
            description="Haven medical assistant persona",
            prompt=PROMPT,
            default=True,
        )

        mk = MedicalKnowledgeTool()
        ws = WebSearchTool()
        rs = RAGSearchTool()

        self.register_tool("medical_kb", mk)
        self.register_tool("web_search", ws)
        self.register_tool("rag_search", rs)

        self.register_lc_tool(StructuredTool.from_function(
            coroutine=mk.__call__,
            name="medical_kb",
            description="Look up medical symptoms and conditions. Args: action (lookup/list), symptom (description string)",
        ))
        self.register_lc_tool(StructuredTool.from_function(
            coroutine=ws.__call__,
            name="web_search",
            description="Search the web for medical information. Args: query (search string)",
        ))
        self.register_lc_tool(StructuredTool.from_function(
            coroutine=rs.__call__,
            name="rag_search",
            description="Search the medical knowledge base. Args: query (search string), top_k (number of results, default 5)",
        ))
