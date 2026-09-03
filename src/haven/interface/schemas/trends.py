from pydantic import BaseModel


class TrendResponse(BaseModel):
    days: int
    record_count: int
    systolic_avg: float | None = None
    diastolic_avg: float | None = None
    systolic_max: int | None = None
    diastolic_max: int | None = None
    systolic_min: int | None = None
    diastolic_min: int | None = None
    normal_rate: float | None = None
    trend_direction: str
    message: str