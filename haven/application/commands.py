"""健健命令注册表与固定命令文案。

命令即产品的固定选项（0.0.1）：/hello、/help、/consent、/profile、
/trend、/confirm、/cancel、/skip。中文自然说法仍可用（指令层保留同义映射），
但界面提示一律用命令格式，不再出现「回复『某中文短语』」。

路由分工：
- /hello：**按状态三选一**的文案（未同意 / 已同意未建档 / 已建档），由
  CommandMiddleware 在模型前确定性短路；本模块只定义文案，取状态是中间件的事；
- /help：静态文案，同上短路；
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
    C_SKIP: "建档时跳过可选项（称呼 / 身高 / 体重 / 确诊时间）",
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


#: 通用介绍 —— 两个场合用它：① 用户还没同意隐私政策；② `/hello` 读库失败
#: 的兜底。它自带「先 /consent」的下一步指引，所以未同意时直接可用。
HELLO_TEXT = (
    "你好，我是健健，你的私人健康顾问。\n\n"
    f"输入 {C_HELP} 查看全部命令，输入 {C_CONSENT} 同意隐私政策后便可建档和记录血压。"
)

#: 已同意、还没建档 —— 缩短介绍，把话头交给建档，并预告第一问是称呼
#: （US-001 要求"引导式建档"「5 分钟内完成」，先说来几项能降低放弃率）。
HELLO_NEW_USER_TEXT = (
    "你好，我是健健，你的私人健康顾问。\n\n"
    f"输入 {C_PROFILE} 建档，我会一项一项引导你。"
)


def hello_returning_text(nickname: str | None = None) -> str:
    """已建档用户的 /hello —— 带称呼的简短介绍。"""
    who = f"{nickname}，" if nickname else ""
    return (
        f"{who}你好！我是健健，你的私人健康顾问。\n\n"
        "需要记录血压或查看趋势随时告诉我。"
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
