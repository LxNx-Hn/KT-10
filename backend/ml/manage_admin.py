"""Explicitly grant or revoke administrator access for an existing Kakao user."""
from __future__ import annotations

import argparse

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import User
from app.settings import settings


def set_admin(database_url: str, kakao_id: str, *, is_admin: bool) -> dict:
    normalized = kakao_id.strip()
    if not normalized.isdigit() or int(normalized) <= 0 or len(normalized) > 64:
        raise ValueError("Kakao ID must be a positive numeric identifier.")
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with Session(engine) as db:
            user = db.scalar(select(User).where(User.kakao_id == normalized))
            if user is None:
                raise LookupError(
                    "The Kakao user does not exist. Complete Kakao login once first."
                )
            changed = user.is_admin != is_admin
            user.is_admin = is_admin
            db.commit()
            return {"userId": user.id, "isAdmin": user.is_admin, "changed": changed}
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Grant or revoke KT-10 administrator permission.",
    )
    parser.add_argument("--kakao-id", required=True)
    parser.add_argument(
        "--confirm-kakao-id",
        required=True,
        help="Must exactly match --kakao-id to prevent targeting mistakes.",
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--grant", action="store_true")
    action.add_argument("--revoke", action="store_true")
    args = parser.parse_args()

    if args.kakao_id != args.confirm_kakao_id:
        parser.error("--confirm-kakao-id must exactly match --kakao-id.")
    if not settings.database_url.startswith("postgresql+psycopg://"):
        parser.error("DATABASE_URL must use postgresql+psycopg://.")

    try:
        result = set_admin(
            settings.database_url,
            args.kakao_id,
            is_admin=args.grant,
        )
    except (LookupError, ValueError) as exc:
        parser.error(str(exc))
    state = "granted" if result["isAdmin"] else "revoked"
    change = "changed" if result["changed"] else "already in requested state"
    print(f"Administrator permission {state} ({change}); userId={result['userId']}")


if __name__ == "__main__":
    main()
