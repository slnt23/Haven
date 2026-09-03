from langchain_core.prompts import ChatPromptTemplate

from haven.llm.client import _make_model, is_available

RESPONSE_SYSTEM_PROMPT = """你是一个叫"健健"的个人慢病管理助手，服务于高血压患者。

你的角色定位：
- 提供健康生活建议，但不做医疗诊断
- 语气温暖、专业、简洁
- 每次回复控制在 3-5 句话以内
- 遇到紧急情况，提醒用户立即就医

重要约束：
- 不要说"你患了"、"你得了"等诊断性表述
- 不要建议具体药物或剂量
- 不要替代医生的专业判断
- 如果用户描述紧急症状（胸痛、呼吸困难等），立即说"请立即拨打 120"

请根据以下操作结果，生成自然的回复。"""

_response_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", RESPONSE_SYSTEM_PROMPT),
        (
            "user",
            "用户说：{user_message}\n\n系统操作结果：{action_result}\n\n请生成回复：",
        ),
    ]
)


async def generate_response(
    user_message: str,
    action_result: str,
) -> str:
    if not is_available():
        return action_result

    model = _make_model(temperature=0.7, max_tokens=512)
    chain = _response_prompt | model

    try:
        reply = await chain.ainvoke(
            {
                "user_message": user_message,
                "action_result": action_result,
            }
        )
        return reply.content.strip() if hasattr(reply, "content") else str(reply).strip()
    except Exception:
        return action_result