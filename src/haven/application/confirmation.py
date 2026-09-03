from dataclasses import dataclass

from haven.application.validation import validate_blood_pressure


@dataclass(frozen=True)
class ConfirmationResult:
    needs_confirmation: bool
    systolic: int
    diastolic: int
    message: str
    confirmed: bool | None = None


def check_abnormal(
    systolic: int,
    diastolic: int,
    heart_rate: int | None = None,
) -> ConfirmationResult:
    validation = validate_blood_pressure(systolic, diastolic, heart_rate)

    if not validation.is_valid:
        return ConfirmationResult(
            needs_confirmation=False,
            systolic=systolic,
            diastolic=diastolic,
            message="；".join(validation.errors),
        )

    if not validation.needs_confirmation:
        return ConfirmationResult(
            needs_confirmation=False,
            systolic=systolic,
            diastolic=diastolic,
            message="",
        )

    if validation.is_severe:
        message = (
            f"您输入的血压值为 {systolic}/{diastolic} mmHg，"
            f"属于严重异常范围。"
            f"请确认测量是否正确。如确认无误，建议立即就医。"
        )
    else:
        message = (
            f"您输入的血压值为 {systolic}/{diastolic} mmHg，"
            f"这个数值偏高。确认无误吗？"
        )

    return ConfirmationResult(
        needs_confirmation=True,
        systolic=systolic,
        diastolic=diastolic,
        message=message,
    )


def confirm_abnormal(result: ConfirmationResult, confirmed: bool) -> ConfirmationResult:
    return ConfirmationResult(
        needs_confirmation=result.needs_confirmation,
        systolic=result.systolic,
        diastolic=result.diastolic,
        message=result.message,
        confirmed=confirmed,
    )