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


def utc_now_naive() -> datetime:
    """DB의 기존 timestamp without time zone 계약에 맞춘 UTC 시각."""
    return datetime.now(UTC).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    kakao_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    nickname: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    # passive_deletes: 사용자 삭제 시 ORM이 자식 FK를 NULL로 바꾸려 하지 않고
    # DB의 ON DELETE CASCADE에 맡긴다. user_preferences.user_id는 기본키라
    # blank-out이 불가능하고, 파기 정책은 애초에 DB 외래키가 담당한다.
    preference: Mapped["UserPreference | None"] = relationship(
        back_populates="user",
        uselist=False,
        passive_deletes=True,
    )
    agreements: Mapped[list["UserAgreement"]] = relationship(
        back_populates="user",
        passive_deletes=True,
    )


class UserWithdrawal(Base):
    """탈퇴 기록의 분리 보관소.

    계정·프로필·서비스 데이터는 탈퇴 시점에 즉시 삭제하거나 익명화한다.
    여기에는 부정 가입·탈퇴 반복 방지와 처리 오류 대응에 필요한 최소 정보만
    보관기간 동안 남는다.

    ``users``를 참조하는 외래키를 두지 않는다. 사용자 행이 이미 지워진 뒤에도
    남아야 하는 기록이므로, 외래키가 있으면 CASCADE로 함께 사라진다.
    """

    __tablename__ = "user_withdrawals"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    # 삭제된 users.id. 처리 상태 추적과 문의 대응에 쓰는 내부 식별자이며,
    # 사용자 행이 사라진 뒤에는 그 자체로 개인을 특정하지 못한다.
    user_ref: Mapped[str] = mapped_column(String(36), index=True)
    # sha256(salt + 공급자 회원번호). 같은 사람의 반복 탈퇴만 판별하고
    # 회원번호는 남기지 않는다. salt가 설정되지 않으면 역산이 가능한 약한
    # 해시를 만들지 않고 미보관(None)으로 둔다.
    subject_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    # 파기 예정 시각. 신청 시점의 보관기간으로 고정해, 나중에 설정을 바꿔도
    # 이미 신청한 사용자의 약속된 기한이 흔들리지 않게 한다.
    purge_after: Mapped[datetime] = mapped_column(DateTime, index=True)
    # completed: 삭제와 공급자 연결 끊기까지 끝난 상태
    # provider_unlink_pending: 삭제는 끝났고 연결 끊기만 재시도가 남은 상태
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    # 연결 끊기에 실패했을 때만 재시도를 위해 예외적으로 보관하는 회원번호.
    # 재시도가 성공하면 즉시 지운다.
    pending_provider_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )


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
        DateTime, default=utc_now_naive, onupdate=utc_now_naive
    )
    user: Mapped[User] = relationship(back_populates="preference")


class UserAgreement(Base):
    """현재 공개 이용약관 수락 기록.

    개인정보처리방침 고지나 학습 동의(training_consent)와 섞지 않는다.
    탈퇴 시 users CASCADE로 함께 삭제한다. 별도 분리 보관 대상이 아니다.
    """

    __tablename__ = "user_agreements"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "document_type",
            "document_version",
            "action",
            name="uq_user_agreements_user_doc_version_action",
        ),
        CheckConstraint(
            "document_type IN ('terms')",
            name="ck_user_agreements_document_type",
        ),
        CheckConstraint(
            "action IN ('accepted')",
            name="ck_user_agreements_action",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    document_type: Mapped[str] = mapped_column(String(32))
    document_version: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(32))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    user: Mapped[User] = relationship(back_populates="agreements")


class RouteImpression(Base):
    __tablename__ = "route_impressions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    # 탈퇴 시 함께 삭제한다. profile과 feature_snapshot에 이동 경로와 프로필이
    # 남아 user_id만 끊어서는 익명화됐다고 보기 어렵고, 짝이 되는 후기가 함께
    # 삭제되므로 학습 데이터로도 쓸 수 없다.
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    route_id: Mapped[str] = mapped_column(String(120), index=True)
    model_version: Mapped[str] = mapped_column(String(64), default="rules-v1")
    profile: Mapped[str] = mapped_column(String(16), default="general")
    rank: Mapped[int] = mapped_column(Integer)
    feature_snapshot: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


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
    moderation_status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


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


def new_session() -> Session:
    """의존성 주입 밖(배치 스크립트 등)에서 쓰는 단발 세션.

    호출자가 commit/rollback과 close를 직접 책임진다.
    """
    return _factory()()


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
