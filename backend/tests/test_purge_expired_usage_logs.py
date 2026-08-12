"""이용기록 보유기간 파기 계약.

route_impressions는 계정이 살아 있어도 무기한 남으면 안 된다. 보유기간이
지난 기록은 파기하되, 후기가 달린 기록은 후기 보관 정책을 따른다.
"""
from __future__ import annotations

import importlib.util
import json
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import (
    Base,
    RouteImpression,
    RouteReview,
    User,
    utc_now_naive,
)
from app.settings import settings

ROOT = Path(__file__).resolve().parents[2]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "purge_expired_usage_logs",
        ROOT / "scripts" / "purge_expired_usage_logs.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _impression(engine, *, impression_id, age_days, with_review=False):
    with Session(engine) as db:
        if db.get(User, "member") is None:
            db.add(User(id="member", kakao_id="7001"))
            db.flush()
        db.add(RouteImpression(
            id=impression_id,
            user_id="member",
            route_id="route-1",
            profile="general",
            rank=1,
            feature_snapshot=json.dumps({"avg_slope_percent": 2.0}),
            created_at=utc_now_naive() - timedelta(days=age_days),
        ))
        db.flush()
        if with_review:
            db.add(RouteReview(
                id=f"review-{impression_id}",
                user_id="member",
                impression_id=impression_id,
                route_id="route-1",
                was_usable=True,
                rating=4,
                training_consent=True,
            ))
        db.commit()


@pytest.fixture()
def purge_env(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite+pysqlite:///{(tmp_path / 'usage.sqlite3').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    module = _load_module()
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(module, "new_session", lambda: factory())
    monkeypatch.setattr(settings, "usage_log_retention_days", 365)
    monkeypatch.setattr(
        settings,
        "database_url",
        "postgresql+psycopg://user:pw@localhost:5432/kt10",
    )
    return module, engine


def test_usage_log_past_retention_is_purged(purge_env):
    module, engine = purge_env
    _impression(engine, impression_id="old", age_days=400)

    summary = module.purge(dry_run=False)

    assert summary["purged"] == 1
    with Session(engine) as db:
        assert db.get(RouteImpression, "old") is None


def test_usage_log_inside_retention_is_kept(purge_env):
    module, engine = purge_env
    _impression(engine, impression_id="recent", age_days=364)

    summary = module.purge(dry_run=False)

    assert summary["expiredCount"] == 0
    with Session(engine) as db:
        assert db.get(RouteImpression, "recent") is not None


def test_reviewed_usage_log_follows_the_review_policy(purge_env):
    """후기의 피처 스냅샷은 후기 기록의 일부라 함께 지우지 않는다."""
    module, engine = purge_env
    _impression(engine, impression_id="reviewed", age_days=400, with_review=True)

    summary = module.purge(dry_run=False)

    assert summary["keptWithReview"] == 1
    assert summary["purged"] == 0
    with Session(engine) as db:
        assert db.get(RouteImpression, "reviewed") is not None


def test_dry_run_does_not_delete(purge_env):
    module, engine = purge_env
    _impression(engine, impression_id="old", age_days=400)

    summary = module.purge(dry_run=True)

    assert summary["dryRun"] is True and summary["purged"] == 1
    with Session(engine) as db:
        assert db.get(RouteImpression, "old") is not None


def test_zero_retention_skips_instead_of_deleting_everything(purge_env, monkeypatch):
    """보유기간을 정의하지 않은 상태에서 임의 기준으로 지우지 않는다."""
    module, engine = purge_env
    monkeypatch.setattr(settings, "usage_log_retention_days", 0)
    _impression(engine, impression_id="old", age_days=4000)

    summary = module.purge(dry_run=False)

    assert summary["status"] == "skipped"
    with Session(engine) as db:
        assert db.get(RouteImpression, "old") is not None
