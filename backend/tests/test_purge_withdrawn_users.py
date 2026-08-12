"""보관기간 파기 배치의 기록 삭제와 밀린 연결 끊기 재시도 계약.

계정 데이터는 탈퇴 시점에 이미 사라졌다. 이 배치는 남은 최소 기록을
보관기간 후에 지우고, 실패했던 공급자 연결 끊기를 재시도한다.
"""
from __future__ import annotations

import importlib.util
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, UserWithdrawal, utc_now_naive
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


def _record(engine, *, record_id, purge_after, status="completed", provider_id=None):
    with Session(engine) as db:
        db.add(UserWithdrawal(
            id=record_id,
            user_ref=f"user-{record_id}",
            subject_hash="0" * 64,
            purge_after=purge_after,
            status=status,
            pending_provider_id=provider_id,
        ))
        db.commit()


@pytest.fixture()
def purge_env(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite+pysqlite:///{(tmp_path / 'purge.sqlite3').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
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


def test_expired_record_is_purged(purge_env):
    module, engine = purge_env
    _record(engine, record_id="old", purge_after=utc_now_naive() - timedelta(seconds=1))

    summary = module.purge(dry_run=False)

    assert summary["purged"] == 1
    with Session(engine) as db:
        assert db.get(UserWithdrawal, "old") is None


def test_record_inside_retention_window_is_kept(purge_env):
    module, engine = purge_env
    _record(engine, record_id="fresh", purge_after=utc_now_naive() + timedelta(days=30))

    summary = module.purge(dry_run=False)

    assert summary["dueCount"] == 0
    with Session(engine) as db:
        assert db.get(UserWithdrawal, "fresh") is not None


def test_dry_run_reports_targets_without_deleting(purge_env):
    module, engine = purge_env
    _record(engine, record_id="old", purge_after=utc_now_naive() - timedelta(seconds=1))

    summary = module.purge(dry_run=True)

    assert summary["dryRun"] is True and summary["purged"] == 1
    with Session(engine) as db:
        assert db.get(UserWithdrawal, "old") is not None


def test_pending_unlink_is_retried_and_provider_id_dropped(purge_env, monkeypatch):
    """재시도가 성공하면 예외적으로 보관하던 회원번호를 더 들고 있지 않는다."""
    module, engine = purge_env
    _record(
        engine,
        record_id="pending",
        purge_after=utc_now_naive() + timedelta(days=29),
        status="provider_unlink_pending",
        provider_id="7001",
    )

    async def succeeding_unlink(_kakao_id):
        return True

    monkeypatch.setattr(module, "unlink_kakao_account", succeeding_unlink)

    summary = module.purge(dry_run=False)

    assert summary["unlinkRecovered"] == 1
    assert summary["unlinkStillFailing"] == 0
    with Session(engine) as db:
        record = db.get(UserWithdrawal, "pending")
        assert record.status == "completed"
        assert record.pending_provider_id is None


def test_still_failing_unlink_is_reported(purge_env, monkeypatch):
    module, engine = purge_env
    _record(
        engine,
        record_id="pending",
        purge_after=utc_now_naive() + timedelta(days=29),
        status="provider_unlink_pending",
        provider_id="7001",
    )

    async def failing_unlink(_kakao_id):
        return False

    monkeypatch.setattr(module, "unlink_kakao_account", failing_unlink)

    summary = module.purge(dry_run=False)

    assert summary["unlinkStillFailing"] == 1
    with Session(engine) as db:
        # 기한 전이므로 기록은 남고 재시도 근거도 유지된다.
        assert db.get(UserWithdrawal, "pending").pending_provider_id == "7001"


def test_retention_limit_wins_over_unfinished_unlink(purge_env, monkeypatch):
    """보관기간은 상한이라 연결 끊기가 끝나지 않아도 연장하지 않는다."""
    module, engine = purge_env
    _record(
        engine,
        record_id="stuck",
        purge_after=utc_now_naive() - timedelta(seconds=1),
        status="provider_unlink_pending",
        provider_id="7001",
    )

    async def failing_unlink(_kakao_id):
        return False

    monkeypatch.setattr(module, "unlink_kakao_account", failing_unlink)

    summary = module.purge(dry_run=False)

    assert summary["purged"] == 1
    # 카카오 연결이 남은 채 기록만 사라지므로 운영자가 알 수 있어야 한다.
    assert summary["purgedWithUnlinkPending"] == 1
    with Session(engine) as db:
        assert db.scalar(select(UserWithdrawal)) is None
