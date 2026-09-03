from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from haven.domain.models import AllergyRecord, DiseaseRecord, HealthProfile


@dataclass(frozen=True)
class ProfileData:
    gender: str
    birth_date: date
    height_cm: float | None = None
    weight_kg: float | None = None
    smoking_status: str | None = None
    alcohol_frequency: str | None = None
    exercise_frequency: str | None = None
    diet_preference: str | None = None


@dataclass(frozen=True)
class DiseaseData:
    disease_name: str
    diagnosed_date: date
    severity: str | None = None
    status: str = "Active"
    notes: str | None = None


@dataclass(frozen=True)
class AllergyData:
    allergen: str
    allergy_type: str
    severity: str | None = None
    reaction: str | None = None


@dataclass(frozen=True)
class OnboardingResult:
    profile: HealthProfile
    diseases: list[DiseaseRecord]
    allergies: list[AllergyRecord]


async def create_profile(
    session: AsyncSession,
    user_id: UUID,
    data: ProfileData,
) -> HealthProfile:
    existing = await session.execute(
        select(HealthProfile).where(HealthProfile.user_id == user_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise ValueError("HealthProfile already exists for this user")

    profile = HealthProfile(
        user_id=user_id,
        gender=data.gender,
        birth_date=data.birth_date,
        height_cm=data.height_cm,
        weight_kg=data.weight_kg,
        smoking_status=data.smoking_status,
        alcohol_frequency=data.alcohol_frequency,
        exercise_frequency=data.exercise_frequency,
        diet_preference=data.diet_preference,
    )
    session.add(profile)
    await session.commit()
    return profile


async def get_profile(
    session: AsyncSession,
    user_id: UUID,
) -> HealthProfile | None:
    stmt = select(HealthProfile).where(HealthProfile.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def update_profile(
    session: AsyncSession,
    user_id: UUID,
    data: ProfileData,
) -> HealthProfile:
    profile = await get_profile(session, user_id)
    if profile is None:
        raise ValueError("HealthProfile not found")

    profile.gender = data.gender
    profile.birth_date = data.birth_date
    profile.height_cm = data.height_cm
    profile.weight_kg = data.weight_kg
    profile.smoking_status = data.smoking_status
    profile.alcohol_frequency = data.alcohol_frequency
    profile.exercise_frequency = data.exercise_frequency
    profile.diet_preference = data.diet_preference
    await session.commit()
    return profile


async def add_disease(
    session: AsyncSession,
    user_id: UUID,
    data: DiseaseData,
) -> DiseaseRecord:
    record = DiseaseRecord(
        user_id=user_id,
        disease_name=data.disease_name,
        diagnosed_date=data.diagnosed_date,
        severity=data.severity,
        status=data.status,
        notes=data.notes,
    )
    session.add(record)
    await session.commit()
    return record


async def get_diseases(
    session: AsyncSession,
    user_id: UUID,
) -> list[DiseaseRecord]:
    stmt = select(DiseaseRecord).where(DiseaseRecord.user_id == user_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def add_allergy(
    session: AsyncSession,
    user_id: UUID,
    data: AllergyData,
) -> AllergyRecord:
    record = AllergyRecord(
        user_id=user_id,
        allergen=data.allergen,
        allergy_type=data.allergy_type,
        severity=data.severity,
        reaction=data.reaction,
    )
    session.add(record)
    await session.commit()
    return record


async def get_allergies(
    session: AsyncSession,
    user_id: UUID,
) -> list[AllergyRecord]:
    stmt = select(AllergyRecord).where(AllergyRecord.user_id == user_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def complete_onboarding(
    session: AsyncSession,
    user_id: UUID,
    profile_data: ProfileData,
    diseases: list[DiseaseData] | None = None,
    allergies: list[AllergyData] | None = None,
) -> OnboardingResult:
    profile = await create_profile(session, user_id, profile_data)

    disease_records: list[DiseaseRecord] = []
    if diseases:
        for d in diseases:
            record = await add_disease(session, user_id, d)
            disease_records.append(record)

    allergy_records: list[AllergyRecord] = []
    if allergies:
        for a in allergies:
            record = await add_allergy(session, user_id, a)
            allergy_records.append(record)

    return OnboardingResult(
        profile=profile,
        diseases=disease_records,
        allergies=allergy_records,
    )