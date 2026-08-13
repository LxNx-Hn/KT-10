"""이용약관 수락 기록. 서버가 current version의 유일한 출처다.

이 식별자는 법적 시행일이 아니다. training_consent·개인정보 고지와 분리한다.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import User, UserAgreement

# 공개 이용약관의 machine-readable 기술 버전. 시행일·updatedAt이 아니다.
CURRENT_TERMS_VERSION = "v1"
DOCUMENT_TYPE_TERMS = "terms"
AGREEMENT_ACTION_ACCEPTED = "accepted"


def has_current_terms_agreement(db: Session, user: User) -> bool:
    """현재 서버 이용약관 버전의 accepted 기록이 있으면 True."""
    return db.scalar(
        select(UserAgreement.id).where(
            UserAgreement.user_id == user.id,
            UserAgreement.document_type == DOCUMENT_TYPE_TERMS,
            UserAgreement.document_version == CURRENT_TERMS_VERSION,
            UserAgreement.action == AGREEMENT_ACTION_ACCEPTED,
        ).limit(1)
    ) is not None


def consume_current_terms_agreement(db: Session, user: User) -> bool:
    """이번 요청이 current accepted 행을 새로 만들었으면 True.

    이미 있거나 동시 요청이 UNIQUE로 먼저 넣은 경우는 False다.
    signup complete는 True인 요청에만 session을 발급한다.
    """
    if has_current_terms_agreement(db, user):
        return False
    try:
        with db.begin_nested():
            db.add(UserAgreement(
                user_id=user.id,
                document_type=DOCUMENT_TYPE_TERMS,
                document_version=CURRENT_TERMS_VERSION,
                action=AGREEMENT_ACTION_ACCEPTED,
            ))
            db.flush()
        return True
    except IntegrityError:
        if has_current_terms_agreement(db, user):
            return False
        raise
