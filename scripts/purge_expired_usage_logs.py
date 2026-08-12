"""보유기간이 지난 이용기록(추천 표시 기록)을 파기한다.

``route_impressions``는 추천을 화면에 보여줄 때마다 쌓이는 이용기록이다.
탈퇴하면 함께 삭제되지만, 계정이 살아 있으면 무기한 남는다. 보유기간을
정하고 그 기간이 지난 기록은 계정과 무관하게 파기한다.

후기가 달린 이용기록은 제외한다. 후기의 피처 스냅샷으로 쓰이는 후기 기록의
일부이고, 학습 동의라는 별도 근거와 보관 정책을 따르기 때문이다. 남는 것은
후기가 없는 순수 이용기록뿐이다.

운영에서는 외부 스케줄러(cron 등)로 하루 1회 실행한다.

usage:
    python scripts/purge_expired_usage_logs.py --dry-run
    python scripts/purge_expired_usage_logs.py
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.database import (  # noqa: E402
    RouteImpression,
    RouteReview,
    new_session,
    utc_now_naive,
)
from app.settings import settings  # noqa: E402
from sqlalchemy import select  # noqa: E402


def purge(*, dry_run: bool) -> dict:
    """보유기간이 지난 이용기록을 파기하고 결과 요약을 돌려준다."""
    if not settings.database_configured:
        raise SystemExit("PostgreSQL이 설정되지 않아 파기를 실행할 수 없습니다.")
    retention_days = settings.usage_log_retention_days
    if retention_days <= 0:
        # 보유기간을 정의하지 않은 상태에서 임의 기준으로 지우지 않는다.
        return {
            "status": "skipped",
            "reason": "usage-log-retention-not-configured",
            "dryRun": dry_run,
        }

    session = new_session()
    now = utc_now_naive()
    cutoff = now - timedelta(days=retention_days)
    purged = 0
    kept_with_review = 0
    try:
        expired = list(session.scalars(
            select(RouteImpression).where(RouteImpression.created_at < cutoff)
        ))
        reviewed_ids = set(session.scalars(
            select(RouteReview.impression_id).where(
                RouteReview.impression_id.is_not(None)
            )
        ))
        for impression in expired:
            if impression.id in reviewed_ids:
                # 후기 기록의 일부라 후기 보관 정책을 따른다.
                kept_with_review += 1
                continue
            purged += 1
            if not dry_run:
                session.delete(impression)

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
        "retentionDays": retention_days,
        "cutoff": cutoff.isoformat(),
        "expiredCount": len(expired),
        "purged": purged,
        "keptWithReview": kept_with_review,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="보유기간이 지난 이용기록을 파기합니다.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="삭제하지 않고 대상만 집계합니다.",
    )
    args = parser.parse_args()
    print(json.dumps(purge(dry_run=args.dry_run), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
