"""健健命令注册表与固定命令文案。

命令即产品的固定选项（0.0.1）：/hello、/help、/consent、/profile、
/trend、/confirm、/cancel、/skip。中文自然说法仍可用（指令层保留同义映射），
但界面提示一律用命令格式，不再出现「回复『某中文短语』」。

路由分工：
- /hello、/help：静态文案，由 CommandMiddleware 在模型前确定性短路；
- /consent、/cancel：异步路径确定性处理（同中间件）；
- /profile、/trend、/confirm、/skip：依赖对话上下文或人工批准
  （interrupt_on），由模型路由到工具，下游仍有确定性闸门。

本模块不 import application/messages，保持零循环依赖。
"""

from __future__ import annotations

# ── 命令 token（单处定义，各处引用） ──
C_HELLO = "/hello"
C_HELP = "/help"
C_CONSENT = "/consent"
C_PROFILE = "/profile"
C_TREND = "/trend"
C_CONFIRM = "/confirm"
C_CANCEL = "/cancel"
C_SKIP = "/skip"

#: 顺序即 /help 展示顺序。
COMMANDS: dict[str, str] = {
    C_HELLO: "项目介绍 —— 健健是什么、能做什么、怎么开始",
    C_HELP: "本列表 —— 全部命令的用法与作用",
    C_CONSENT: "同意隐私政策 —— 建档与记录健康数据前的第一步",
    C_PROFILE: "创建或更新健康档案（0.0.1 支持高血压）",
    C_TREND: "查看最近 7 天的血压趋势",
    C_CONFIRM: "确认当前待保存内容（异常血压 / 建档摘要 / 数据删除）",
    C_CANCEL: "取消当前操作（不保存）",
    C_SKIP: "建档时跳过可选项（身高 / 体重 / 确诊时间）",
}

#: 中间件在模型前确定性处理的命令。
STATIC_COMMANDS: frozenset[str] = frozenset((C_HELLO, C_HELP))

#: 异步路径确定性处理（写库）的命令。
DETERMINISTIC_COMMANDS: frozenset[str] = frozenset((C_CONSENT, C_CANCEL))


def match_command(text: str) -> str | None:
    """消息整条恰为命令（去首尾空白）→ 返回命令；否则 None。"""
    token = text.strip()
    if token in COMMANDS:
        return token
    return None


HELLO_TEXT = (
    "您好，欢迎使用健健（Haven）—— 您的健康管家。\n\n"
    "我来帮您打理血压健康：\n"
    f"· 健康建档 —— {C_PROFILE}\n"
    "· 记录血压 —— 直接告诉我数值，如 120/80\n"
    f"· 七日趋势 —— {C_TREND}\n"
    "· 数据删除 —— 对我说「删除我的数据」\n\n"
    "隐私与边界：健健不是医疗设备，不提供医疗诊断、处方或治疗建议；"
    "您的健康数据按账号隔离保存，可随时删除。"
    "如遇紧急情况，请立即拨打 120。\n\n"
    f"开始使用：先 {C_CONSENT} 同意隐私政策，然后 {C_PROFILE} 建档。\n"
    f"完整命令列表：{C_HELP}"
)


def help_text() -> str:
    lines = ["健健命令总览（中文说法同样有效）：", ""]
    for token, purpose in COMMANDS.items():
        lines.append(f"· {token} —— {purpose}")
    lines += [
        "",
        "除命令外直接自然交流即可：报血压「128/84」、日期「1950-03-12」、",
        "要求「删除我的数据」都能识别。紧急情况请立即拨打 120。",
    ]
    return "\n".join(lines)
