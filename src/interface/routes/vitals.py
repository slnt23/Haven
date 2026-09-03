from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from haven.application.confirmation import check_abnormal
from haven.application.consent import has_consented
from haven.application.validation import validate_blood_pressure
from haven.application.vitals import (
    BloodPressureData,
    check_duplicate,
    record_blood_pressure,
)
from haven.interface.deps import get_current_user_id, get_db
from haven.interface.schemas.vitals import (
    BloodPressureRecordResponse,
    BloodPressureRequest,
    BloodPressureResponse,
)

router = APIRouter(prefix="/api/vitals", tags=["vitals"])


async def _require_consent(session: AsyncSession, user_id: UUID) -> None:
    if not await has_consented(session, user_id):
        raise HTTPException(
            status_code=403,
            detail="请先阅读并同意隐私政策后再使用该功能",
        )


@router.post("/blood-pressure", response_model=BloodPressureRecordResponse, status_code=201)
async def record_bp(
    body: BloodPressureRequest,
    session: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> BloodPressureRecordResponse:
    await _require_consent(session, user_id)

    validation = validate_blood_pressure(body.systolic, body.diastolic, body.heart_rate)
    if not validation.is_valid:
        raise HTTPException(
            status_code=422,
            detail={"errors": validation.errors},
        )

    if body.measured_at:
        is_dup = await check_duplicate(
            session,
            user_id,
            body.systolic,
            body.diastolic,
            body.measured_at,
        )
        if is_dup:
            raise HTTPException(
                status_code=409,
                detail="重复提交：相同血压值在 60 秒内已记录",
            )

    confirmation = check_abnormal(body.systolic, body.diastolic, body.heart_rate)
    if confirmation.needs_confirmation:
        return BloodPressureRecordResponse(
            record=BloodPressureResponse(
                record_id=UUID("00000000-0000-0000-0000-000000000000"),
                user_id=user_id,
                systolic=body.systolic,
                diastolic=body.diastolic,
                heart_rate=body.heart_rate,
                measured_at=body.measured_at,
                source=body.source,
                is_abnormal=True,
                notes=body.notes,
                created_at=body.measured_at,
            ),
            is_abnormal=True,
            needs_confirmation=True,
            confirmation_message=confirmation.message,
        )

    record = await record_blood_pressure(
        session,
        user_id,
        BloodPressureData(
            systolic=body.systolic,
            diastolic=body.diastolic,
            measured_at=body.measured_at,
            heart_rate=body.heart_rate,
            source=body.source,
            notes=body.notes,
        ),
    )

    return BloodPressureRecordResponse(
        record=BloodPressureResponse.model_validate(record),
        is_abnormal=validation.is_abnormal,
        needs_confirmation=False,
    )


@router.post("/blood-pressure/confirm", response_model=BloodPressureRecordResponse, status_code=201)
async def confirm_bp(
    body: BloodPressureRequest,
    session: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> BloodPressureRecordResponse:
    await _require_consent(session, user_id)

    confirmation = check_abnormal(body.systolic, body.diastolic, body.heart_rate)
    if not confirmation.needs_confirmation:
        raise HTTPException(
            status_code=400,
            detail="该血压值不需要二次确认",
        )

    record = await record_blood_pressure(
        session,
        user_id,
        BloodPressureData(
            systolic=body.systolic,
            diastolic=body.diastolic,
            measured_at=body.measured_at,
            heart_rate=body.heart_rate,
            source=body.source,
            notes=body.notes,
        ),
    )

    return BloodPressureRecordResponse(
        record=BloodPressureResponse.model_validate(record),
        is_abnormal=True,
        needs_confirmation=False,
    )