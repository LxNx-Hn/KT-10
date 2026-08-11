"""보관기간 파기 배치의 삭제 범위와 실패 정책.

users 행 하나를 지우면 기존 외래키 정책이 나머지를 정리한다는 전제 위에
서 있으므로, 그 전제가 실제로 지켜지는지 함께 검증한다.
"""
from __future__ import annotations

import importlib.util
import json
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.database import (
    Base,
    FacilityReport,
    RouteImpression,
    RouteReview,
    User,
    UserPreference,
    UserWithdrawal,
    utc_now_naive,
)
from app.settings import settings

ROOT = Path(__file__).resolve().parents[2]


def _load_purge_module():
    spec = importlib.util.spec_from_file_location(
        "purge_withdrawn_users",
        ROOT / "scripts" / "purge_withdrawn_users.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _engine(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{(tmp_path / 'purge.sqlite3').as_posix()}",
        connect_args={"check_same_thread": False},
    )

    # 파기가 CASCADE·SET NULL에 의존하므로 SQLite에서도 외래키를 켠다.
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return engine


def _seed_withdrawn_user(engine, *, user_id, purge_after, provider_unlinked=True):
    with Session(engine) as db:
        user = User(id=user_id, kakao_id=f"kakao-{user_id}", nickname=None)
        db.add(user)
        db.flush()
        db.add(UserPreference(user_id=user.id, profile="elderly"))
        impression = RouteImpression(
            id=f"impression-{user_id}",
            user_id=user.id,
            route_id="route-1",
            profile="elderly",
            rank=1,
            feature_snapshot=json.dumps({"avg_slope_percent": 2.0}),
        )
        db.add(impression)
        db.flush()
        db.add(RouteReview(
            id=f"review-{user_id}",
            user_id=user.id,
            impression_id=impression.id,
            route_id="route-1",
            was_usable=True,
            rating=4,
        ))
        db.add(FacilityReport(
            id=f"report-{user_id}",
            user_id=user.id,
            facility_name="부산역 1번 승강기",
            facility_type="elevator",
            issue_type="broken",
            description="승강기가 고장났습니다.",
        ))
        db.add(UserWithdrawal(
            user_id=user.id,
            purge_after=purge_after,
            provider_unlinked=provider_unlinked,
        ))
        db.commit()


@pytest.fixture()
def purge_env(tmp_path, monkeypatch):
    engine = _engine(tmp_path)
    module = _load_purge_module()
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(module, "new_session", lambda: factory())
    monkeypatch.setattr(settings, "withdrawal_retention_days", 30)
    monkeypatch.setattr(
        settings,
        "database_url",
        "postgresql+psycopg://user:pw@localhost:5432/kt10",
    )
    return module, engine


def test_expired_account_is_purged_with_the_declared_fk_policy(purge_env):
    module, engine = purge_env
    _seed_withdrawn_user(
        engine,
        user_id="expired",
        purge_after=utc_now_naive() - timedelta(seconds=1),
    )

    summary = module.purge(dry_run=False)

    assert summary["purged"] == 1
    with Session(engine) as db:
        # 사용자와 대기열 항목은 사라진다.
        assert db.get(User, "expired") is None
        assert db.get(UserWithdrawal, "expired") is None
        # 개인 설정과 후기는 함께 삭제된다(CASCADE).
        assert db.get(UserPreference, "expired") is None
        assert db.get(RouteReview, "review-expired") is None
        # 공익적 기록은 익명으로 보존된다(SET NULL).
        impression = db.get(RouteImpression, "impression-expired")
        assert impression is not None
        assert impression.user_id is None
        report = db.get(FacilityReport, "report-expired")
        assert report is not None
        assert report.user_id is None
        assert report.description == "승강기가 고장났습니다."


def test_account_inside_retention_window_is_kept(purge_env):
    module, engine = purge_env
    _seed_withdrawn_user(
        engine,
        user_id="pending",
        purge_after=utc_now_naive() + timedelta(days=30),
    )

    summary = module.purge(dry_run=False)

    assert summary["dueCount"] == 0
    assert summary["purged"] == 0
    with Session(engine) as db:
        assert db.get(User, "pending") is not None
        assert db.get(UserWithdrawal, "pending") is not None


def test_dry_run_reports_targets_without_deleting(purge_env):
    module, engine = purge_env
    _seed_withdrawn_user(
        engine,
        user_id="expired",
        purge_after=utc_now_naive() - timedelta(seconds=1),
    )

    summary = module.purge(dry_run=True)

    assert summary["dryRun"] is True
    assert summary["purged"] == 1
    with Session(engine) as db:
        assert db.get(User, "expired") is not None
        assert db.get(UserWithdrawal, "expired") is not None


def test_unlink_retry_success_allows_purge(purge_env, monkeypatch):
    module, engine = purge_env
    _seed_withdrawn_user(
        engine,
        user_id="retry",
        purge_after=utc_now_naive() - timedelta(seconds=1),
        provider_unlinked=False,
    )

    async def succeeding_unlink(_kakao_id):
        return True

    monkeypatch.setattr(module, "unlink_kakao_account", succeeding_unlink)

    summary = module.purge(dry_run=False)

    assert summary["unlinkRetried"] == 1
    assert summary["purged"] == 1
    with Session(engine) as db:
        assert db.get(User, "retry") is None


def test_unlink_retry_failure_keeps_the_account_queued(purge_env, monkeypatch):
    """카카오 연결이 남은 채로 우리 기록만 지우지 않는다."""
    module, engine = purge_env
    _seed_withdrawn_user(
        engine,
        user_id="stuck",
        purge_after=utc_now_naive() - timedelta(seconds=1),
        provider_unlinked=False,
    )

    async def failing_unlink(_kakao_id):
        return False

    monkeypatch.setattr(module, "unlink_kakao_account", failing_unlink)

    summary = module.purge(dry_run=False)

    assert summary["skippedUnlinkFailed"] == 1
    assert summary["purged"] == 0
    with Session(engine) as db:
        assert db.get(User, "stuck") is not None
        assert db.get(UserWithdrawal, "stuck") is not None
