from pydantic import BaseModel, Field

from haven.llm.client import _make_model, is_available

INTENT_SYSTEM_PROMPT = """你是一个医疗健康助手的意图识别模块。根据用户输入，识别意图并提取参数。

支持的意图：
- record_blood_pressure: 用户想记录血压。提取 systolic（收缩压）、diastolic（舒张压）、heart_rate（心率，可选）
- view_trend: 用户想查看血压趋势
- give_consent: 用户同意隐私政策
- create_profile: 用户想建档或更新健康信息
- greeting: 用户打招呼
- ask_help: 用户询问功能
- general_question: 一般健康问题

规则：
1. 如果用户提供了血压数值，intent 必须是 record_blood_pressure，params 中提取 systolic 和 diastolic
2. 血压数值的常见表达：120/80、高压120低压80、收缩压120舒张压80
3. 如果无法确定意图，使用 general_question
4. confidence 表示你对意图判断的置信度"""


class IntentClassification(BaseModel):
    intent: str = Field(description="意图名称，如 record_blood_pressure、view_trend、give_consent、create_profile、greeting、ask_help、general_question")
    params: dict = Field(default_factory=dict, description="提取的参数，如 systolic、diastolic、heart_rate")
    confidence: float = Field(description="置信度，0.0 到 1.0")


class IntentResult:
    __slots__ = ("confidence", "intent", "params")

    def __init__(self, intent: str, params: dict | None = None, confidence: float = 0.0) -> None:
        self.intent = intent
        self.params = params or {}
        self.confidence = confidence


async def classify_intent(user_message: str) -> IntentResult:
    if not is_available():
        return IntentResult(intent="unavailable")

    model = _make_model(temperature=0.1, max_tokens=512)
    structured_model = model.with_structured_output(IntentClassification, method="json_mode")

    messages = [
        {"role": "system", "content": INTENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    try:
        result: IntentClassification = await structured_model.ainvoke(messages)
        return IntentResult(
            intent=result.intent,
            params=result.params,
            confidence=result.confidence,
        )
    except Exception:
        return IntentResult(intent="unavailable")