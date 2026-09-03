from dataclasses import dataclass, field
from enum import Enum


class ValidationLevel(Enum):
    NORMAL = "normal"
    HIGH_NORMAL = "high_normal"
    GRADE_1 = "grade_1"
    GRADE_2 = "grade_2"
    GRADE_3 = "grade_3"
    SEVERE = "severe"


@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    systolic: int
    diastolic: int
    systolic_level: ValidationLevel = ValidationLevel.NORMAL
    diastolic_level: ValidationLevel = ValidationLevel.NORMAL
    errors: list[str] = field(default_factory=list)

    @property
    def is_abnormal(self) -> bool:
        return self.systolic_level not in (
            ValidationLevel.NORMAL,
            ValidationLevel.HIGH_NORMAL,
        ) or self.diastolic_level not in (
            ValidationLevel.NORMAL,
            ValidationLevel.HIGH_NORMAL,
        )

    @property
    def is_severe(self) -> bool:
        return (
            self.systolic_level == ValidationLevel.SEVERE
            or self.diastolic_level == ValidationLevel.SEVERE
        )

    @property
    def needs_confirmation(self) -> bool:
        return (
            self.systolic_level
            in (ValidationLevel.GRADE_2, ValidationLevel.GRADE_3, ValidationLevel.SEVERE)
            or self.diastolic_level
            in (ValidationLevel.GRADE_2, ValidationLevel.GRADE_3, ValidationLevel.SEVERE)
        )


SYSTOLIC_MIN = 60
SYSTOLIC_MAX = 300
DIASTOLIC_MIN = 30
DIASTOLIC_MAX = 200
HEART_RATE_MIN = 30
HEART_RATE_MAX = 250


def classify_systolic(value: int) -> ValidationLevel:
    if value < 120:
        return ValidationLevel.NORMAL
    if value < 140:
        return ValidationLevel.HIGH_NORMAL
    if value < 160:
        return ValidationLevel.GRADE_1
    if value < 180:
        return ValidationLevel.GRADE_2
    if value < 220:
        return ValidationLevel.GRADE_3
    return ValidationLevel.SEVERE


def classify_diastolic(value: int) -> ValidationLevel:
    if value < 80:
        return ValidationLevel.NORMAL
    if value < 90:
        return ValidationLevel.HIGH_NORMAL
    if value < 100:
        return ValidationLevel.GRADE_1
    if value < 110:
        return ValidationLevel.GRADE_2
    if value < 130:
        return ValidationLevel.GRADE_3
    return ValidationLevel.SEVERE


def validate_blood_pressure(
    systolic: int,
    diastolic: int,
    heart_rate: int | None = None,
) -> ValidationResult:
    errors: list[str] = []

    if systolic < SYSTOLIC_MIN or systolic > SYSTOLIC_MAX:
        errors.append(
            f"收缩压必须在 {SYSTOLIC_MIN}-{SYSTOLIC_MAX} mmHg 之间，"
            f"收到 {systolic}"
        )

    if diastolic < DIASTOLIC_MIN or diastolic > DIASTOLIC_MAX:
        errors.append(
            f"舒张压必须在 {DIASTOLIC_MIN}-{DIASTOLIC_MAX} mmHg 之间，"
            f"收到 {diastolic}"
        )

    if systolic <= diastolic:
        errors.append(
            f"收缩压 ({systolic}) 必须大于舒张压 ({diastolic})"
        )

    if heart_rate is not None and (
        heart_rate < HEART_RATE_MIN or heart_rate > HEART_RATE_MAX
    ):
        errors.append(
            f"心率必须在 {HEART_RATE_MIN}-{HEART_RATE_MAX} bpm 之间，"
            f"收到 {heart_rate}"
        )

    if errors:
        return ValidationResult(
            is_valid=False,
            systolic=systolic,
            diastolic=diastolic,
            errors=errors,
        )

    return ValidationResult(
        is_valid=True,
        systolic=systolic,
        diastolic=diastolic,
        systolic_level=classify_systolic(systolic),
        diastolic_level=classify_diastolic(diastolic),
    )