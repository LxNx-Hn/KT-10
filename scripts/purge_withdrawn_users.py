"""보관기간이 지난 탈퇴 기록을 파기하고, 밀린 공급자 연결 끊기를 재시도한다.

``POST /api/auth/withdraw``는 계정·프로필·서비스 데이터를 그 자리에서 즉시
삭제한다. 남는 것은 부정 가입·탈퇴 반복 방지와 처리 오류 대응에 필요한 최소
정보뿐이고, 이 스크립트가 두 가지 뒤처리를 맡는다.

1. 카카오 연결 끊기에 실패해 ``provider_unlink_pending``으로 남은 기록을
   재시도한다. 성공하면 예외적으로 보관하던 회원번호를 즉시 지운다.
2. ``purge_after``가 지난 기록을 삭제한다. 보관기간은 지켜야 하는 상한이므로,
   연결 끊기가 끝내 실패해도 기한이 지나면 기록을 남기지 않는다. 이 경우
   카카오 연결이 남을 수 있어 경고를 남긴다.

운영에서는 외부 스케줄러(cron 등)로 하루 1회 실행한다.

usage:
    python scripts/purge_withdrawn_users.py --dry-run
    python scripts/purge_withdrawn_users.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.api.auth import unlink_kakao_account  # noqa: E402
from app.database import (  # noqa: E402
    UserWithdrawal,
    new_session,
    utc_now_naive,
)
from app.settings import settings  # noqa: E402
from sqlalchemy import select  # noqa: E402

log = logging.getLogger("scripts.purge_withdrawn_users")


def _retry_pending_unlinks(session, *, dry_run: bool) -> tuple[int, int]:
    """연결 끊기가 밀린 기록을 재시도한다. (성공, 남은 실패)"""
    pending = list(session.scalars(
        select(UserWithdrawal).where(
            UserWithdrawal.status == "provider_unlink_pending"
        )
    ))
    recovered = 0
    still_failing = 0
    for record in pending:
        if not record.pending_provider_id:
            # 회원번호 없이 재시도할 방법이 없다. 기한까지 두고 파기한다.
            still_failing += 1
            continue
        if dry_run:
            recovered += 1
            continue
        if asyncio.run(unlink_kakao_account(record.pending_provider_id)):
            record.status = "completed"
            # 재시도 목적이 끝났으므로 회원번호를 더 들고 있지 않는다.
            record.pending_provider_id = None
            recovered += 1
        else:
            still_failing += 1
    return recovered, still_failing


def purge(*, dry_run: bool) -> dict:
    """밀린 연결 끊기를 재시도하고 기한이 지난 기록을 파기한다."""
    if not settings.database_configured:
        raise SystemExit("PostgreSQL이 설정되지 않아 파기를 실행할 수 없습니다.")

    session = new_session()
    now = utc_now_naive()
    purged = 0
    purged_with_unlink_pending = 0
    due: list[UserWithdrawal] = []
    try:
        unlink_recovered, unlink_failed = _retry_pending_unlinks(
            session, dry_run=dry_run
        )

        due = list(session.scalars(
            select(UserWithdrawal).where(UserWithdrawal.purge_after <= now)
        ))
        for record in due:
            if record.status != "completed":
                # 보관기간은 상한이라 연장하지 않는다. 카카오 연결이 남은 채로
                # 기록만 사라지므로 운영자가 알 수 있게 경고한다.
                purged_with_unlink_pending += 1
                log.warning(
                    "연결 끊기 미완료 상태로 보관기간이 만료되어 기록을 "
                    "파기합니다 (user_ref=%s)",
                    record.user_ref,
                )
            purged += 1
            if not dry_run:
                session.delete(record)

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
        "unlinkRecovered": unlink_recovered,
        "unlinkStillFailing": unlink_failed,
        "dueCount": len(due),
        "purged": purged,
        "purgedWithUnlinkPending": purged_with_unlink_pending,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="보관기간이 지난 탈퇴 기록을 파기합니다.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="삭제하지 않고 대상만 집계합니다.",
    )
    args = parser.parse_args()
    summary = purge(dry_run=args.dry_run)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["unlinkStillFailing"] or summary["purgedWithUnlinkPending"]:
        # 운영 스케줄러가 실패를 감지할 수 있도록 종료 코드를 남긴다.
        raise SystemExit(1)


if __name__ == "__main__":
    main()
