"""PostgreSQL persistence for Kakao users, preferences, route impressions, and reviews.

No SQLite fallback is provided: review data must never silently become local-only
when a production PostgreSQL URL was expected.
"""
from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from .settings import settings


class Base(DeclarativeBase):
    pass


def _utc_now_naive() -> datetime:
    """DB의 기존 timestamp without time zone 계약에 맞춘 UTC 시각."""
    return datetime.now(UTC).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    kakao_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    nickname: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now_naive)
    preference: Mapped["UserPreference | None"] = relationship(back_populates="user", uselist=False)


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    profile: Mapped[str] = mapped_column(String(16), default="general")
    uses_wheelchair: Mapped[bool] = mapped_column(Boolean, default=False)
    uses_walking_aid: Mapped[bool] = mapped_column(Boolean, default=False)
    visual_support_required: Mapped[bool] = mapped_column(Boolean, default=False)
    hearing_support_required: Mapped[bool] = mapped_column(Boolean, default=False)
    avoid_stairs_required: Mapped[bool] = mapped_column(Boolean, default=False)
    max_walk_distance_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    training_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    personalization_state: Mapped[str] = mapped_column(Text, default='{"version":1,"bias":0.0,"weights":{},"updates":0}')
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utc_now_naive, onupdate=_utc_now_naive
    )
    user: Mapped[User] = relationship(back_populates="preference")


class RouteImpression(Base):
    __tablename__ = "route_impressions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    route_id: Mapped[str] = mapped_column(String(120), index=True)
    model_version: Mapped[str] = mapped_column(String(64), default="rules-v1")
    profile: Mapped[str] = mapped_column(String(16), default="general")
    rank: Mapped[int] = mapped_column(Integer)
    feature_snapshot: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now_naive)


class RouteReview(Base):
    __tablename__ = "route_reviews"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "impression_id",
            name="uq_route_reviews_user_impression",
        ),
        CheckConstraint(
            "crowding_difficulty IS NULL OR crowding_difficulty BETWEEN 1 AND 5",
            name="ck_route_reviews_crowding_difficulty_range",
        ),
        CheckConstraint(
            "transfer_information_difficulty IS NULL "
            "OR transfer_information_difficulty BETWEEN 1 AND 5",
            name="ck_route_reviews_transfer_information_difficulty_range",
        ),
        CheckConstraint(
            "accessibility_facility_difficulty IS NULL "
            "OR accessibility_facility_difficulty BETWEEN 1 AND 5",
            name="ck_route_reviews_accessibility_facility_difficulty_range",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    impression_id: Mapped[str | None] = mapped_column(ForeignKey("route_impressions.id", ondelete="SET NULL"), nullable=True)
    route_id: Mapped[str] = mapped_column(String(120), index=True)
    was_usable: Mapped[bool] = mapped_column(Boolean)
    rating: Mapped[int] = mapped_column(Integer)
    issue_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stairs_difficulty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    slope_difficulty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transfer_difficulty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    crowding_difficulty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transfer_information_difficulty: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    accessibility_facility_difficulty: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    actual_duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    would_reuse: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    information_accurate: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    training_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now_naive)


class FacilityReport(Base):
    """User report for a facility whose recorded location/status is inaccurate.

    Reports are evidence for moderation, never an automatic overwrite of source data.
    """
    __tablename__ = "facility_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    facility_name: Mapped[str] = mapped_column(String(200))
    facility_type: Mapped[str] = mapped_column(String(64))
    issue_type: Mapped[str] = mapped_column(String(64))
    reported_lat: Mapped[float | None] = mapped_column(nullable=True)
    reported_lng: Mapped[float | None] = mapped_column(nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now_naive)


_session_factory: sessionmaker[Session] | None = None


def _factory() -> sessionmaker[Session]:
    global _session_factory
    if not settings.database_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL is not configured.",
        )
    if _session_factory is None:
        engine = create_engine(settings.database_url, pool_pre_ping=True)
        _session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return _session_factory


def init_database() -> None:
    """PostgreSQL 스키마를 Alembic 최신 revision으로 올린다."""
    from alembic import command
    from alembic.config import Config

    config_path = Path(__file__).resolve().parents[1] / "alembic.ini"
    config = Config(str(config_path))
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    command.upgrade(config, "head")


def database_session() -> Generator[Session, None, None]:
    session = _factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def optional_database_session() -> Generator[Session | None, None, None]:
    """게스트 요청은 DB 미설정 상태에서도 동작하고, 설정된 경우에만 세션을 연다."""
    if not settings.database_configured:
        yield None
        return
    session = _factory()()
    try:
        yield session
    finally:
        session.close()
