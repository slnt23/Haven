from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from haven.application.consent import has_consented
from haven.application.onboarding import (
    AllergyData,
    DiseaseData,
    OnboardingResult,
    ProfileData,
    complete_onboarding,
    get_diseases,
    get_profile,
    update_profile,
)
from haven.interface.deps import get_current_user_id, get_db
from haven.interface.schemas.profile import (
    AllergyResponse,
    DiseaseResponse,
    OnboardingRequest,
    OnboardingResponse,
    ProfileRequest,
    ProfileResponse,
)

router = APIRouter(prefix="/api/profile", tags=["profile"])


async def _require_consent(session: AsyncSession, user_id: UUID) -> None:
    if not await has_consented(session, user_id):
        raise HTTPException(
            status_code=403,
            detail="请先阅读并同意隐私政策后再使用该功能",
        )


@router.post("/onboarding", response_model=OnboardingResponse, status_code=201)
async def onboard(
    body: OnboardingRequest,
    session: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> OnboardingResponse:
    await _require_consent(session, user_id)

    p = body.profile
    profile_data = ProfileData(
        gender=p.gender,
        birth_date=p.birth_date,
        height_cm=p.height_cm,
        weight_kg=p.weight_kg,
        smoking_status=p.smoking_status,
        alcohol_frequency=p.alcohol_frequency,
        exercise_frequency=p.exercise_frequency,
        diet_preference=p.diet_preference,
    )

    diseases = [
        DiseaseData(
            disease_name=d.disease_name,
            diagnosed_date=d.diagnosed_date,
            severity=d.severity,
            status=d.status,
        )
        for d in body.diseases
    ]

    allergies = [
        AllergyData(
            allergen=a.allergen,
            allergy_type=a.allergy_type,
            severity=a.severity,
            reaction=a.reaction,
        )
        for a in body.allergies
    ]

    result = await complete_onboarding(
        session,
        user_id,
        profile_data,
        diseases=diseases if diseases else None,
        allergies=allergies if allergies else None,
    )

    return _to_onboarding_response(result)


@router.get("", response_model=ProfileResponse)
async def get_my_profile(
    session: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> ProfileResponse:
    profile = await get_profile(session, user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="未找到健康画像，请先完成建档")
    return ProfileResponse.model_validate(profile)


@router.put("", response_model=ProfileResponse)
async def update_my_profile(
    body: ProfileRequest,
    session: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> ProfileResponse:
    profile = await update_profile(
        session,
        user_id,
        ProfileData(
            gender=body.gender,
            birth_date=body.birth_date,
            height_cm=body.height_cm,
            weight_kg=body.weight_kg,
            smoking_status=body.smoking_status,
            alcohol_frequency=body.alcohol_frequency,
            exercise_frequency=body.exercise_frequency,
            diet_preference=body.diet_preference,
        ),
    )
    return ProfileResponse.model_validate(profile)


@router.get("/diseases", response_model=list[DiseaseResponse])
async def get_my_diseases(
    session: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> list[DiseaseResponse]:
    records = await get_diseases(session, user_id)
    return [DiseaseResponse.model_validate(r) for r in records]


def _to_onboarding_response(result: OnboardingResult) -> OnboardingResponse:
    return OnboardingResponse(
        profile=ProfileResponse.model_validate(result.profile),
        diseases=[DiseaseResponse.model_validate(d) for d in result.diseases],
        allergies=[AllergyResponse.model_validate(a) for a in result.allergies],
    )