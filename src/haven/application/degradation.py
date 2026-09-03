from dataclasses import dataclass


@dataclass(frozen=True)
class DegradationResult:
    degraded: bool
    message: str
    safe_response: str = ""


LLM_DEGRADED_RESPONSE: str = (
    "抱歉，我暂时无法处理您的请求，请稍后再试。"
    "如有紧急情况，请立即拨打 120。"
)

DB_DEGRADED_RESPONSE: str = (
    "抱歉，系统暂时无法访问您的健康数据，请稍后再试。"
    "如有紧急情况，请立即拨打 120。"
)


def handle_llm_degradation() -> DegradationResult:
    return DegradationResult(
        degraded=True,
        message="LLM service unavailable",
        safe_response=LLM_DEGRADED_RESPONSE,
    )


def handle_db_degradation() -> DegradationResult:
    return DegradationResult(
        degraded=True,
        message="Database unavailable",
        safe_response=DB_DEGRADED_RESPONSE,
    )


def is_degraded(error: Exception) -> bool:
    return True