from pydantic import BaseModel, Field

from haven.llm.client import _make_model, is_available
from haven.llm.prompts import load_prompt


class IntentClassification(BaseModel):
    intent: str = Field(description="意图名称，如 record_blood_pressure、view_trend、give_consent、create_profile、greeting、ask_help、general_question")
    params: dict = Field(default_factory=dict, description="提取的参数，如 systolic、diastolic")
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
    structured_model = model.with_structured_output(IntentClassification, method="function_calling")

    messages = [
        {"role": "system", "content": load_prompt("intent_classifier")},
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