"""建档字段的词表、状态机与逐字段校验 —— 纯确定性，绝不 LLM。

**封闭词表**：`STEP_ORDER` 的字段名与 `save_health_profile` 的参数名逐一对应，
建档草稿工具只接受这六个取值，模型不能自由发挥（B3「可续接」依赖这个不变量）。

字段常量与日期解析原先散在 `tools/onboarding.py` / `tools/_helpers.py`，
现集中到本模块：**建档草稿（保存中）与正式建档（保存时）共用同一套校验**，
避免两处各判一次、判出不同结果。错误文案与 `save_health_profile` 原有口径一致。
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

#: 建档顺序 —— 即状态机游标（`OnboardingDraft.next_field`）的取值域。
STEP_ORDER: tuple[str, ...] = (
    "gender",
    "birth_date",
    "height_cm",
    "weight_kg",
    "disease_name",
    "diagnosed_date",
)

#: 可跳过项 —— 与 instructions.md §五 的「可跳过」标记一致。
SKIPPABLE: frozenset[str] = frozenset({"height_cm", "weight_kg", "diagnosed_date"})

STEP_LABELS: dict[str, str] = {
    "gender": "性别",
    "birth_date": "出生日期",
    "height_cm": "身高",
    "weight_kg": "体重",
    "disease_name": "健康问题",
    "diagnosed_date": "确诊时间",
}

GENDERS = ("男", "女")
BIRTH_MIN = date(1900, 1, 1)
HEIGHT_MIN, HEIGHT_MAX = 80, 250
WEIGHT_MIN, WEIGHT_MAX = 2, 500
SUPPORTED_DISEASE = "高血压"

#: 单字段入库前的长度上限 —— 字段值最终会被注入 system prompt，
#: 限长 + 去控制字符是为了让用户可控的文本撑不破记忆块。
MAX_FIELD_CHARS = 64

_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def next_step(step: str) -> str | None:
    """下一步的字段名；已是最后一步返回 None。"""
    index = STEP_ORDER.index(step)
    if index + 1 < len(STEP_ORDER):
        return STEP_ORDER[index + 1]
    return None


def fmt_num(value: float) -> str:
    """170.0 -> 170；170.5 原样。档案展示与记忆块共用。"""
    return f"{value:.0f}" if float(value).is_integer() else f"{value}"


def clean_value(raw: object) -> str:
    """入库前的确定性清洗：去控制字符与换行、压缩空白、截断到上限。

    字段值会被拼进 **system prompt** 里的记忆块，那是比用户轮次更高权限的
    通道，所以清洗发生在写入侧（这里）而不只是读取侧。
    """
    text = _CONTROL.sub(" ", str(raw))
    return " ".join(text.split())[:MAX_FIELD_CHARS]


def parse_date(text: str, *, allow_year_only: bool = False) -> date | None:
    """解析日期文本：ISO、中文年月日、或纯年份（allow_year_only）。"""
    if not text:
        return None
    text = text.strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.match(r"^(\d{4})年\s*(\d{1,2})月(?:\s*(\d{1,2})日)?$", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1))
        except ValueError:
            return None
    if allow_year_only:
        m = re.match(r"^(\d{4})$", text)
        if m:
            try:
                return date(int(m.group(1)), 1, 1)
            except ValueError:
                return None
    return None


def _to_float(text: str) -> float | None:
    """取文本里的第一个数字（容忍「170」「170.5」「170cm」「170 厘米」）。"""
    m = _NUMBER.search(text)
    if m is None:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None


def _missing(step: str) -> tuple[None, str]:
    """未提供值：可跳过项放行，必填项拒绝。"""
    return None, f"「{STEP_LABELS[step]}」是必填项，不能跳过。请重新询问这一项。"


def validate_step(step: str, raw: object | None = None) -> tuple[object | None, str | None]:
    """校验建档单步输入 → ``(归一化值, 错误文案)``，两者互斥。

    ``raw`` 为 None / 空串表示「用户没有提供」（跳过或没听懂）：
    可跳过项返回 ``(None, None)``，必填项返回错误文案。

    归一化值：gender → str，birth_date / diagnosed_date → date，
    height_cm / weight_kg → float，disease_name → str。
    """
    if step not in STEP_ORDER:
        return None, f"未知的建档项「{clean_value(step)}」。合法取值：{'、'.join(STEP_ORDER)}。"

    text = clean_value(raw) if raw is not None else ""
    if not text:
        if step in SKIPPABLE:
            return None, None
        return _missing(step)

    if step == "gender":
        if text not in GENDERS:
            return None, f"性别只能填写「男」或「女」，收到「{text}」。请确认后重试。"
        return text, None

    if step == "birth_date":
        parsed = parse_date(text, allow_year_only=True)
        if parsed is None or parsed < BIRTH_MIN or parsed > date.today():
            return (
                None,
                f"出生日期需在 {BIRTH_MIN.isoformat()} 到今天的范围内，收到「{text}」。"
                "请按 1950-03-12 的格式重试。",
            )
        return parsed, None

    if step == "height_cm":
        value = _to_float(text)
        if value is None or not (HEIGHT_MIN <= value <= HEIGHT_MAX):
            return None, f"身高需在 {HEIGHT_MIN}-{HEIGHT_MAX} 厘米之间，收到 {text}。请确认后重试。"
        return value, None

    if step == "weight_kg":
        value = _to_float(text)
        if value is None or not (WEIGHT_MIN <= value <= WEIGHT_MAX):
            return None, f"体重需在 {WEIGHT_MIN}-{WEIGHT_MAX} 公斤之间，收到 {text}。请确认后重试。"
        return value, None

    if step == "disease_name":
        if text != SUPPORTED_DISEASE:
            return None, "0.0.1 版本仅支持登记高血压。"
        return text, None

    # diagnosed_date
    parsed = parse_date(text, allow_year_only=True)
    if parsed is None:
        return (
            None,
            f"确诊时间无法识别（收到「{text}」，示例 2020-05 或 2020-05-01），请重试。",
        )
    if parsed > date.today():
        return None, f"确诊时间不能晚于今天（收到 {parsed.isoformat()}），请确认后重试。"
    return parsed, None


def age_on(birth: date, today: date | None = None) -> int:
    """周岁 —— 记忆块展示用（确定性，不引入 LLM 估算）。"""
    moment = today or datetime.now(UTC).date()
    years = moment.year - birth.year
    if (moment.month, moment.day) < (birth.month, birth.day):
        years -= 1
    return years
