from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from haven.application.trends import format_trend_message, get_seven_day_trend
from haven.interface.deps import get_current_user_id, get_db
from haven.interface.schemas.trends import TrendResponse

router = APIRouter(prefix="/api/trends", tags=["trends"])


@router.get("/blood-pressure", response_model=TrendResponse)
async def get_bp_trend(
    session: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> TrendResponse:
    summary = await get_seven_day_trend(session, user_id)
    message = format_trend_message(summary)

    return TrendResponse(
        days=summary.days,
        record_count=summary.record_count,
        systolic_avg=summary.systolic_avg,
        diastolic_avg=summary.diastolic_avg,
        systolic_max=summary.systolic_max,
        diastolic_max=summary.diastolic_max,
        systolic_min=summary.systolic_min,
        diastolic_min=summary.diastolic_min,
        normal_rate=summary.normal_rate,
        trend_direction=summary.trend_direction,
        message=message,
    )