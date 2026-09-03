from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field


class ProfileRequest(BaseModel):
    gender: str = Field(min_length=1, max_length=10)
    birth_date: date
    height_cm: float | None = Field(default=None, ge=50, le=250)
    weight_kg: float | None = Field(default=None, ge=2, le=500)
    smoking_status: str | None = Field(default=None, max_length=20)
    alcohol_frequency: str | None = Field(default=None, max_length=20)
    exercise_frequency: str | None = Field(default=None, max_length=10)
    diet_preference: str | None = Field(default=None, max_length=100)


class DiseaseRequest(BaseModel):
    disease_name: str = Field(min_length=1, max_length=100)
    diagnosed_date: date
    severity: str | None = Field(default=None, max_length=20)
    status: str = Field(default="Active", max_length=20)
    notes: str | None = Field(default=None)


class AllergyRequest(BaseModel):
    allergen: str = Field(min_length=1, max_length=100)
    allergy_type: str = Field(min_length=1, max_length=20)
    severity: str | None = Field(default=None, max_length=20)
    reaction: str | None = Field(default=None)


class OnboardingRequest(BaseModel):
    profile: ProfileRequest
    diseases: list[DiseaseRequest] = Field(default_factory=list)
    allergies: list[AllergyRequest] = Field(default_factory=list)


class DiseaseResponse(BaseModel):
    disease_id: UUID
    disease_name: str
    diagnosed_date: date
    severity: str | None
    status: str

    model_config = {"from_attributes": True}


class AllergyResponse(BaseModel):
    allergy_id: UUID
    allergen: str
    allergy_type: str
    severity: str | None

    model_config = {"from_attributes": True}


class ProfileResponse(BaseModel):
    profile_id: UUID
    user_id: UUID
    gender: str
    birth_date: date
    height_cm: float | None
    weight_kg: float | None
    smoking_status: str | None
    alcohol_frequency: str | None
    exercise_frequency: str | None
    diet_preference: str | None

    model_config = {"from_attributes": True}


class OnboardingResponse(BaseModel):
    profile: ProfileResponse
    diseases: list[DiseaseResponse]
    allergies: list[AllergyResponse]