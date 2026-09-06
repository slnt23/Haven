from dataclasses import dataclass
from enum import Enum, auto


class SafetyState(Enum):
    NORMAL = auto()
    EMERGENCY = auto()
    DEGRADED = auto()


VALID_TRANSITIONS: dict[SafetyState, frozenset[SafetyState]] = {
    SafetyState.NORMAL: frozenset({SafetyState.EMERGENCY, SafetyState.DEGRADED}),
    SafetyState.EMERGENCY: frozenset({SafetyState.NORMAL}),
    SafetyState.DEGRADED: frozenset({SafetyState.NORMAL}),
}


@dataclass
class SafetyContext:
    state: SafetyState = SafetyState.NORMAL

    def transition_to(self, target: SafetyState) -> None:
        if target not in VALID_TRANSITIONS.get(self.state, frozenset()):
            raise ValueError(
                f"Invalid state transition: {self.state.name} -> {target.name}"
            )
        self.state = target

    def is_emergency(self) -> bool:
        return self.state == SafetyState.EMERGENCY

    def is_degraded(self) -> bool:
        return self.state == SafetyState.DEGRADED

    def is_normal(self) -> bool:
        return self.state == SafetyState.NORMAL

    def reset(self) -> None:
        self.state = SafetyState.NORMAL


EMERGENCY_LOCKED_ACTIONS: frozenset[str] = frozenset(
    {
        "record_vitals",
        "update_profile",
        "query_trends",
        "chat",
        "knowledge_qa",
    }
)