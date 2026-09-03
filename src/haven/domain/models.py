from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from haven.infrastructure.database import Base


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    username: Mapped[str] = mapped_column(
        String(32),
        unique=True,
        nullable=False,
    )

    password_hash: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
    )

    nickname: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    phone: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        default=True,
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        default=None,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )


class HealthProfile(Base):
    __tablename__ = "health_profiles"

    profile_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.user_id"),
        unique=True,
        nullable=False,
    )

    gender: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )

    birth_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    height_cm: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    weight_kg: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )


class DiseaseRecord(Base):
    __tablename__ = "disease_records"

    disease_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.user_id"),
        nullable=False,
    )

    disease_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    diagnosed_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    severity: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="Active",
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )


class BloodPressure(Base):
    __tablename__ = "blood_pressure_records"

    record_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.user_id"),
        nullable=False,
        index=True,
    )

    systolic: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    diastolic: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    measured_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="Manual",
    )

    is_abnormal: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )


class ConsentRecord(Base):
    __tablename__ = "consent_records"

    consent_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.user_id"),
        nullable=False,
        index=True,
    )

    policy_version: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    scope: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    consented_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )

    ip_address: Mapped[str | None] = mapped_column(
        String(45),
        nullable=True,
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    audit_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.user_id"),
        nullable=True,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    event_summary: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    rule_version: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )
