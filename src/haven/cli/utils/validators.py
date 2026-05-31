"""输入校验。"""

from __future__ import annotations


def validate_model_name(name: str) -> bool:
    if not name or not name.strip():
        return False
    return len(name) <= 100


def validate_skill_name(name: str) -> bool:
    if not name or not name.strip():
        return False
    invalid = set("<>:\"/\\|?*")
    return not any(c in invalid for c in name) and len(name) <= 128


def validate_task(text: str) -> tuple[bool, str]:
    if not text or not text.strip():
        return False, "任务文本不能为空。"
    if len(text) > 100000:
        return False, "任务文本过长（最大 100,000 字符）。"
    return True, ""


def validate_session_id(sid: str) -> bool:
    if not sid or not sid.strip():
        return False
    return len(sid) <= 256 and " " not in sid
