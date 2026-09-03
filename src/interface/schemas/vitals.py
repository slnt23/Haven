from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class BloodPressureRequest(BaseModel):
    systolic: int = Field(ge=60, le=300)
    diastolic: int = Field(ge=30, le=200)
    heart_rate: int | None = Field(default=None, ge=30, le=250)
    measured_at: datetime | None = None
    source: str = Field(default="Manual", max_length=20)
    notes: str | None = Field(default=None)


class BloodPressureResponse(BaseModel):
    record_id: UUID
    user_id: UUID
    systolic: int
    diastolic: int
    heart_rate: int | None
    measured_at: datetime
    source: str
    is_abnormal: bool | None
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class BloodPressureRecordResponse(BaseModel):
    record: BloodPressureResponse
    is_abnormal: bool
    needs_confirmation: bool
    confirmation_message: str | None = None