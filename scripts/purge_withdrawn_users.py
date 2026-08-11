"""보관기간이 지난 탈퇴 신청 계정을 실제로 파기한다.

``POST /api/auth/withdraw``는 사용자를 즉시 지우지 않는다. 로그인만 막고
``user_withdrawals`` 대기열에 파기 예정 시각을 남긴다. 이 스크립트가 기한이
지난 계정의 ``users`` 행을 삭제하면, 그때 외래키 정책이 나머지를 정리한다.

- ``user_preferences``, ``route_reviews``: 함께 삭제(CASCADE)
- ``route_impressions``, ``facility_reports``: 익명으로 보존(SET NULL)

카카오 연결 끊기에 실패했던 계정은 파기 전에 한 번 더 시도한다. 재시도도
실패하면 그 계정은 이번 회차에서 건너뛰고 대기열에 남긴다. 우리 DB에서만
사라지고 카카오 쪽 연결은 남는 상태를 조용히 만들지 않기 위해서다.

운영에서는 외부 스케줄러(cron 등)로 하루 1회 실행한다.

usage:
    python scripts/purge_withdrawn_users.py --dry-run
    python scripts/purge_withdrawn_users.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.api.auth import unlink_kakao_account  # noqa: E402
from app.database import (  # noqa: E402
    User,
    UserWithdrawal,
    new_session,
    utc_now_naive,
)
from app.settings import settings  # noqa: E402
from sqlalchemy import select  # noqa: E402


def _due_withdrawals(session, now):
    return list(session.scalars(
        select(UserWithdrawal).where(UserWithdrawal.purge_after <= now)
    ))


def purge(*, dry_run: bool) -> dict:
    """기한이 지난 탈퇴 계정을 파기하고 결과 요약을 돌려준다."""
    if not settings.database_configured:
        raise SystemExit("PostgreSQL이 설정되지 않아 파기를 실행할 수 없습니다.")

    session = new_session()
    now = utc_now_naive()
    purged = 0
    unlink_retried = 0
    skipped_unlink_failed = 0
    missing_user = 0
    due: list[UserWithdrawal] = []
    try:
        due = _due_withdrawals(session, now)
        for withdrawal in due:
            user = session.get(User, withdrawal.user_id)
            if user is None:
                # 사용자 행이 이미 없으면 대기열 항목만 남은 상태다.
                missing_user += 1
                if not dry_run:
                    session.delete(withdrawal)
                continue

            if not withdrawal.provider_unlinked:
                if dry_run:
                    unlink_retried += 1
                else:
                    unlinked = asyncio.run(unlink_kakao_account(user.kakao_id))
                    if not unlinked:
                        # 카카오 연결이 남은 채로 우리 기록만 지우지 않는다.
                        skipped_unlink_failed += 1
                        continue
                    withdrawal.provider_unlinked = True
                    unlink_retried += 1

            purged += 1
            if not dry_run:
                # users 행 삭제 하나로 CASCADE·SET NULL 정책이 모두 적용된다.
                session.delete(user)

        if dry_run:
            session.rollback()
        else:
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return {
        "status": "ok",
        "dryRun": dry_run,
        "evaluatedAt": now.isoformat(),
        "retentionDays": settings.withdrawal_retention_days,
        "dueCount": len(due),
        "purged": purged,
        "unlinkRetried": unlink_retried,
        "skippedUnlinkFailed": skipped_unlink_failed,
        "missingUser": missing_user,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="보관기간이 지난 탈퇴 계정을 파기합니다.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="삭제하지 않고 대상만 집계합니다.",
    )
    args = parser.parse_args()
    summary = purge(dry_run=args.dry_run)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["skippedUnlinkFailed"]:
        # 운영 스케줄러가 실패를 감지할 수 있도록 종료 코드를 남긴다.
        raise SystemExit(1)


if __name__ == "__main__":
    main()
