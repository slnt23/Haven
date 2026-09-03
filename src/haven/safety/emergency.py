from dataclasses import dataclass
from enum import Enum, auto


class EmergencyLevel(Enum):
    NONE = auto()
    SUSPICIOUS = auto()
    CONFIRMED = auto()


@dataclass(frozen=True)
class EmergencyResult:
    level: EmergencyLevel
    reason: str = ""


EMERGENCY_KEYWORDS: frozenset[str] = frozenset(
    {
        "胸痛",
        "胸闷",
        "呼吸困难",
        "喘不上气",
        "晕厥",
        "晕倒",
        "昏迷",
        "意识不清",
        "剧烈头痛",
        "剧烈腹痛",
        "大出血",
        "吐血",
        "便血",
        "中风",
        "偏瘫",
        "口眼歪斜",
        "心梗",
        "心肌梗死",
        "心脏骤停",
        "窒息",
        "休克",
        "濒死感",
        "快不行了",
        "不行了",
        "要死了",
        "自杀",
        "不想活了",
    }
)

NEGATION_PATTERNS: frozenset[str] = frozenset(
    {
        "没有",
        "不是",
        "不会",
        "没",
        "无",
        "不",
        "别",
        "没有过",
        "从来没",
        "未",
    }
)

THIRD_PERSON_PATTERNS: frozenset[str] = frozenset(
    {
        "他",
        "她",
        "我爸",
        "我妈",
        "我爸爸",
        "我妈妈",
        "我朋友",
        "我同事",
        "我邻居",
        "别人",
        "有人",
    }
)

HYPOTHETICAL_PATTERNS: frozenset[str] = frozenset(
    {
        "如果",
        "假如",
        "假设",
        "万一",
        "要是",
        "比如",
        "例如",
    }
)

EMERGENCY_RESPONSE_CN: str = (
    "请立即拨打 120 急救电话或前往最近医院急诊科就诊。"
    "健健无法处理紧急医疗情况，请务必立即寻求专业医疗帮助。"
)


def detect_emergency(text: str) -> EmergencyResult:
    has_keyword = any(kw in text for kw in EMERGENCY_KEYWORDS)
    if not has_keyword:
        return EmergencyResult(EmergencyLevel.NONE)

    has_negation = any(neg in text for neg in NEGATION_PATTERNS)
    if has_negation:
        return EmergencyResult(EmergencyLevel.SUSPICIOUS, reason="negation_detected")

    has_third_person = any(tp in text for tp in THIRD_PERSON_PATTERNS)
    if has_third_person:
        return EmergencyResult(EmergencyLevel.SUSPICIOUS, reason="third_person_detected")

    has_hypothetical = any(hp in text for hp in HYPOTHETICAL_PATTERNS)
    if has_hypothetical:
        return EmergencyResult(EmergencyLevel.SUSPICIOUS, reason="hypothetical_detected")

    return EmergencyResult(EmergencyLevel.CONFIRMED, reason="keyword_matched")