"""降级文案 —— 固定模板，绝不 LLM 生成。

文案从 `src/haven/application/degradation.py` 原样复刻（丢弃其中的
未接线类，仅保留文案常量）。
"""

LLM_DEGRADED_RESPONSE: str = (
    "抱歉，我暂时无法处理您的请求，请稍后再试。"
    "如有紧急情况，请立即拨打 120。"
)

DB_DEGRADED_RESPONSE: str = (
    "抱歉，系统暂时无法访问您的健康数据，请稍后再试。"
    "如有紧急情况，请立即拨打 120。"
)
