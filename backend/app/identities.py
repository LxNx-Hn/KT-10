"""Provider identity lookup and Kakao dual-write helpers.

users.kakao_id는 transition 동안 유지한다. Apple 등 다른 provider는
legacy kakao_id fallback을 절대 타지 않는다.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import User, UserIdentity

PROVIDER_KAKAO = "kakao"


class ProviderIdentityConflict(Exception):
    """같은 provider subject가 다른 User에 이미 귀속된 상태.

    legacy kakao_id와 UserIdentity owner가 불일치하면 인증을 이어가지 않는다.
    """


def find_identity(
    db: Session,
    *,
    provider: str,
    provider_subject: str,
) -> UserIdentity | None:
    return db.scalar(
        select(UserIdentity).where(
            UserIdentity.provider == provider,
            UserIdentity.provider_subject == provider_subject,
        )
    )


def ensure_kakao_identity(db: Session, user: User) -> None:
    """legacy User에 Kakao identity가 없으면 안전하게 보충한다.

    subject가 다른 User에 이미 묶여 있으면 재연결하지 않고 conflict를 올린다.
    """
    subject = user.kakao_id
    existing = find_identity(
        db,
        provider=PROVIDER_KAKAO,
        provider_subject=subject,
    )
    if existing is not None:
        if existing.user_id != user.id:
            raise ProviderIdentityConflict(
                "Kakao identity is already linked to another user.",
            )
        return
    try:
        with db.begin_nested():
            db.add(UserIdentity(
                user_id=user.id,
                provider=PROVIDER_KAKAO,
                provider_subject=subject,
            ))
            db.flush()
    except IntegrityError as exc:
        # 동시 heal: 재조회 후 owner가 동일할 때만 허용한다.
        existing = find_identity(
            db,
            provider=PROVIDER_KAKAO,
            provider_subject=subject,
        )
        if existing is not None and existing.user_id == user.id:
            return
        raise ProviderIdentityConflict(
            "Kakao identity conflict after unique constraint.",
        ) from exc


def find_user_by_provider_identity(
    db: Session,
    *,
    provider: str,
    provider_subject: str,
) -> User | None:
    """provider subject로 User를 찾는다.

    1) UserIdentity(provider, provider_subject)
    2) provider == kakao 일 때만 users.kakao_id legacy fallback (+ self-heal)

    legacy User와 identity owner가 다르면 ProviderIdentityConflict.
    """
    identity = find_identity(
        db,
        provider=provider,
        provider_subject=provider_subject,
    )
    if identity is not None:
        return db.get(User, identity.user_id)

    if provider != PROVIDER_KAKAO:
        return None

    user = db.scalar(select(User).where(User.kakao_id == provider_subject))
    if user is None:
        return None

    # race: legacy 조회와 heal 사이에 identity가 생기면 owner를 다시 확인한다.
    raced = find_identity(
        db,
        provider=PROVIDER_KAKAO,
        provider_subject=provider_subject,
    )
    if raced is not None:
        if raced.user_id != user.id:
            raise ProviderIdentityConflict(
                "Kakao identity belongs to a different user than legacy kakao_id.",
            )
        return user

    ensure_kakao_identity(db, user)
    return user
