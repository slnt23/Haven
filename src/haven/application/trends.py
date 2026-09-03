from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from haven.application.vitals import get_blood_pressure_records
from haven.domain.models import BloodPressure


@dataclass(frozen=True)
class TrendSummary:
    days: int
    record_count: int
    systolic_avg: float | None = None
    diastolic_avg: float | None = None
    systolic_max: int | None = None
    diastolic_max: int | None = None
    systolic_min: int | None = None
    diastolic_min: int | None = None
    normal_rate: float | None = None
    trend_direction: str = "insufficient_data"
    records: list[BloodPressure] = field(default_factory=list)


def _calculate_trend(records: list[BloodPressure]) -> TrendSummary:
    if not records:
        return TrendSummary(days=0, record_count=0)

    systolic_values = [r.systolic for r in records]
    diastolic_values = [r.diastolic for r in records]

    normal_count = sum(
        1 for s, d in zip(systolic_values, diastolic_values)
        if s < 140 and d < 90
    )

    if len(records) >= 3:
        first_half_s = sum(systolic_values[: len(records) // 2]) / (len(records) // 2)
        second_half_s = sum(systolic_values[len(records) // 2 :]) / (len(records) - len(records) // 2)
        diff = second_half_s - first_half_s
        if diff > 5:
            direction = "rising"
        elif diff < -5:
            direction = "falling"
        else:
            direction = "stable"
    else:
        direction = "insufficient_data"

    return TrendSummary(
        days=0,
        record_count=len(records),
        systolic_avg=round(sum(systolic_values) / len(systolic_values), 1),
        diastolic_avg=round(sum(diastolic_values) / len(diastolic_values), 1),
        systolic_max=max(systolic_values),
        diastolic_max=max(diastolic_values),
        systolic_min=min(systolic_values),
        diastolic_min=min(diastolic_values),
        normal_rate=round(normal_count / len(records) * 100, 1),
        trend_direction=direction,
        records=records,
    )


async def get_seven_day_trend(
    session: AsyncSession,
    user_id: UUID,
) -> TrendSummary:
    since = datetime.now(UTC) - timedelta(days=7)
    records = await get_blood_pressure_records(
        session,
        user_id,
        since=since,
        limit=200,
    )
    records_sorted = sorted(records, key=lambda r: r.measured_at)
    summary = _calculate_trend(records_sorted)
    return TrendSummary(
        days=7,
        record_count=summary.record_count,
        systolic_avg=summary.systolic_avg,
        diastolic_avg=summary.diastolic_avg,
        systolic_max=summary.systolic_max,
        diastolic_max=summary.diastolic_max,
        systolic_min=summary.systolic_min,
        diastolic_min=summary.diastolic_min,
        normal_rate=summary.normal_rate,
        trend_direction=summary.trend_direction,
        records=summary.records,
    )


def format_trend_message(summary: TrendSummary) -> str:
    if summary.record_count == 0:
        return "最近 7 天没有血压记录，请先记录您的血压数据。"

    if summary.record_count < 3:
        return (
            f"最近 7 天仅有 {summary.record_count} 条血压记录，"
            f"数据不足以分析趋势。建议每天早晚各测量一次。"
        )

    direction_text = {
        "rising": "呈上升趋势，请关注",
        "falling": "呈下降趋势",
        "stable": "保持稳定",
        "insufficient_data": "趋势尚不明确",
    }

    msg = (
        f"最近 7 天共 {summary.record_count} 条血压记录：\n"
        f"• 平均血压：{summary.systolic_avg}/{summary.diastolic_avg} mmHg\n"
        f"• 最高血压：{summary.systolic_max}/{summary.diastolic_max} mmHg\n"
        f"• 最低血压：{summary.systolic_min}/{summary.diastolic_min} mmHg\n"
        f"• 达标率：{summary.normal_rate}%\n"
        f"• 趋势：{direction_text.get(summary.trend_direction, summary.trend_direction)}"
    )

    if summary.normal_rate is not None and summary.normal_rate < 50:
        msg += "\n\n您的血压达标率偏低，建议咨询医生调整治疗方案。"

    return msg