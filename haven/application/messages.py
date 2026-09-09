"""固定兜底消息 —— 确定性场景的回复文案统一管理。

值从 `src/haven/agent/messages.py` 原样复刻（保留工具与指令引用的部分）；
0.0.1 命令化后，选项提示统一改用命令 token（单处定义见
`application/commands.py`），中文自然说法仍可用。
"""

from application.commands import (
    C_CANCEL,
    C_CONFIRM,
    C_CONSENT,
    C_HELLO,
    C_HELP,
    C_PROFILE,
    C_TREND,
)


class _Messages:
    __slots__ = ()

    # ── 通用 ──
    empty_input = "请告诉我您的需求，我会尽力帮助您。"
    error_fallback = "抱歉，我暂时无法处理您的请求，请稍后再试。如有紧急情况，请立即拨打 120。"

    # ── 建档 ──
    onboarding_already = f"您的健康档案已存在，可以 {C_PROFILE} 重新建档更新信息。"
    onboarding_interrupted = f"建档流程已中断，请输入 {C_PROFILE} 重新开始。"
    onboarding_cancelled = f"好的，已取消建档。需要时请输入 {C_PROFILE} 重新开始。"
    onboarding_confirm_prompt = (
        f"如需保存请输入 {C_CONFIRM}；如需修改请说明，如「身高170」「出生1960-01-01」。"
    )

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
    consent_required = f"您还没有同意隐私政策。为保护您的健康数据，使用记录/建档前请先同意：请输入 {C_CONSENT}。"
    consent_already = "您已同意过隐私政策，无需重复操作。"
    consent_granted = f"感谢您的同意！现在您可以开始使用了：请输入 {C_PROFILE} 建档，或直接告诉我血压值记录（如 120/80）。"

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
        return (
            f"我注意到您刚才输入的血压 {systolic}/{diastolic} mmHg 偏高，需要您确认："
            f"输入 {C_CONFIRM} 将为您记录，输入 {C_CANCEL} 则不记录。"
        )

    # ── 打招呼 / 帮助 ──
    greeting = (
        "您好！我是健健，您的个人慢病管理助手。我可以帮您：\n"
        f"· 健康建档 — {C_PROFILE}\n"
        "· 记录血压 — 告诉我数值，如 120/80\n"
        f"· 查看趋势 — {C_TREND}\n"
        f"· 项目介绍 — {C_HELLO}　· 全部命令 — {C_HELP}\n"
        f"首次使用请先输入 {C_CONSENT} 同意隐私政策。"
    )
    ask_help = (
        "我可以帮您：\n"
        "· 记录血压 — 直接告诉我血压值，如 120/80\n"
        f"· 查看趋势 — 输入 {C_TREND} 查看七日变化\n"
        f"· 健康建档 — 输入 {C_PROFILE} 创建健康画像\n"
        f"· 隐私同意 — 输入 {C_CONSENT}（可让我先展示政策全文）\n"
        f"· 项目介绍 — {C_HELLO}　· 命令总览 — {C_HELP}\n"
        "有需要随时找我。"
    )


MSG = _Messages()
