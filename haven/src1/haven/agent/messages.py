"""硬编码兜底消息 —— 所有 LLM 不可用时的后备文案，统一管理。

用法：
    from haven.agent.messages import MSG
    return MSG.onboarding_already
"""


class _Messages:
    __slots__ = ()

    # ── 通用 ──
    empty_input = "请告诉我您的需求，我会尽力帮助您。"
    error_fallback = "抱歉，我暂时无法处理您的请求，请稍后再试。如有紧急情况，请立即拨打 120。"

    # ── 建档 ──
    onboarding_already = "您的健康档案已存在，可以重新建档更新信息。"
    onboarding_interrupted = "建档流程已中断，请回复「建档」重新开始。"
    onboarding_cancelled = "好的，已取消建档。需要时回复「建档」重新开始。"
    onboarding_confirm_prompt = "如需保存请回复「确认」；如需修改请说明，如「身高170」「出生1960-01-01」。"

    @staticmethod
    def onboarding_start(field_prompt: str) -> str:
        return f"好的，我来帮您创建健康档案。\n{field_prompt}"

    @staticmethod
    def onboarding_parse_error(field: str, prompt: str) -> str:
        return f"我没能识别「{field}」这一项。{prompt}"

    @staticmethod
    def onboarding_done(gender: str, birth_date: str, disease_name: str) -> str:
        return f"建档完成 ✓ 性别：{gender}，出生：{birth_date}，确诊慢病：{disease_name}。现在可以开始记录血压了，直接告诉我数值即可（如 120/80）。"

    # ── 隐私同意 ──
    consent_required = "您还没有同意隐私政策。为保护您的健康数据，使用记录/建档前请先同意：请回复「同意隐私政策」。"
    consent_already = "您已同意过隐私政策，无需重复操作。"
    consent_granted = "感谢您的同意！现在您可以开始使用了：请先「建档」，或直接告诉我血压值记录（如 120/80）。"

    # ── 血压记录 ──
    bp_invalid = "血压数值不合法，请重新输入"
    bp_cancelled = "好的，这条没有保存。请重新测量后再告诉我数值。"
    bp_need_value = "请告诉我您的血压值，例如：120/80"

    @staticmethod
    def bp_recorded(systolic: int, diastolic: int, level: str) -> str:
        return f"已记录血压 {systolic}/{diastolic} mmHg（{level}）。继续保持监测！"

    @staticmethod
    def bp_confirmed(systolic: int, diastolic: int) -> str:
        return f"已为您记录血压 {systolic}/{diastolic} mmHg。请持续监测。"

    @staticmethod
    def bp_confirm_prompt(systolic: int, diastolic: int) -> str:
        return f"我注意到您刚才输入的血压 {systolic}/{diastolic} mmHg 偏高，需要您确认：回复「确认」将为您记录，回复「取消」则不记录。"

    # ── 打招呼 / 帮助 ──
    greeting = (
        "您好！我是健健，您的个人慢病管理助手。我可以帮您：\n"
        "· 健康建档 — 回复「建档」\n"
        "· 记录血压 — 告诉我数值，如 120/80\n"
        "· 查看趋势 — 回复「血压趋势」\n"
        "首次使用请先回复「同意隐私政策」。"
    )
    ask_help = (
        "我可以帮您：\n"
        "· 记录血压 — 直接告诉我血压值，如 120/80\n"
        "· 查看趋势 — 输入「血压趋势」查看七日变化\n"
        "· 健康建档 — 输入「建档」创建健康画像\n"
        "· 隐私政策 — 输入「隐私政策」查看\n"
        "有需要随时找我。"
    )


MSG = _Messages()