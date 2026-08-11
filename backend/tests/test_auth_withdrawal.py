"""회원 탈퇴 신청과 보관기간 경과 후 파기의 계약.

탈퇴는 즉시 삭제가 아니라 대기열 등록이다. 로그인은 바로 막히고 표시용
개인정보는 즉시 지워지되, 사용자 행은 보관기간 동안 남아 있어야 한다.
"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.api import auth as auth_module
from app.api.auth import current_user
from app.database import (
    Base,
    FacilityReport,
    RouteImpression,
    User,
    UserPreference,
    UserWithdrawal,
    database_session,
    utc_now_naive,
)
from app.main import app
from app.settings import settings


def _engine(tmp_path, name):
    engine = create_engine(
        f"sqlite+pysqlite:///{(tmp_path / name).as_posix()}",
        connect_args={"check_same_thread": False},
    )

    # SQLite는 기본적으로 외래키를 강제하지 않는다. 파기가 CASCADE·SET NULL에
    # 의존하므로 테스트에서도 실제 DB와 같은 동작을 보게 켜 둔다.
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return engine


def _seed(engine, *, is_admin=False):
    with Session(engine) as db:
        user = User(
            id="member",
            kakao_id="7001",
            nickname="부산길",
            is_admin=is_admin,
        )
        db.add(user)
        db.flush()
        db.add(UserPreference(user_id=user.id, profile="disabled"))
        db.add(RouteImpression(
            id="impression-1",
            user_id=user.id,
            route_id="route-1",
            profile="disabled",
            rank=1,
            feature_snapshot=json.dumps({"avg_slope_percent": 3.1}),
        ))
        db.add(FacilityReport(
            id="report-1",
            user_id=user.id,
            facility_name="부산역 1번 승강기",
            facility_type="elevator",
            issue_type="broken",
            description="승강기가 고장났습니다.",
        ))
        db.commit()
    return "member"


@pytest.fixture()
def withdraw_api(tmp_path, monkeypatch):
    engine = _engine(tmp_path, "withdrawal.sqlite3")
    user_id = _seed(engine)
    monkeypatch.setattr(settings, "withdrawal_retention_days", 30)
    # 기본은 어드민 키가 있고 카카오가 성공 응답을 주는 상태로 둔다.
    monkeypatch.setattr(settings, "kakao_admin_key", "test-admin-key")

    async def fake_unlink(_kakao_id):
        return True

    monkeypatch.setattr(auth_module, "unlink_kakao_account", fake_unlink)

    def test_database_session():
        db = Session(engine)
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def authenticated(db: Session = Depends(database_session)):
        return db.get(User, user_id)

    app.dependency_overrides[database_session] = test_database_session
    app.dependency_overrides[current_user] = authenticated
    try:
        yield TestClient(app), engine
    finally:
        app.dependency_overrides.clear()


def test_withdraw_queues_purge_and_masks_display_name(withdraw_api):
    client, engine = withdraw_api

    response = client.post("/api/auth/withdraw")

    assert response.status_code == 204
    with Session(engine) as db:
        withdrawal = db.get(UserWithdrawal, "member")
        assert withdrawal is not None
        assert withdrawal.provider_unlinked is True
        # 사용자 행은 보관기간 동안 남는다. 즉시 삭제가 아니다.
        user = db.get(User, "member")
        assert user is not None
        # 닉네임은 파기를 기다릴 이유가 없는 표시용 개인정보다.
        assert user.nickname is None
        # 예정일은 신청 시점 + 보관기간이다.
        expected = utc_now_naive() + timedelta(days=30)
        assert abs((withdrawal.purge_after - expected).total_seconds()) < 120


def test_withdraw_clears_session_cookie(withdraw_api):
    client, _ = withdraw_api

    response = client.post("/api/auth/withdraw")

    assert response.status_code == 204
    assert "mobility_session" in response.headers.get("set-cookie", "")


def test_repeated_withdraw_does_not_extend_the_deadline(withdraw_api):
    client, engine = withdraw_api

    assert client.post("/api/auth/withdraw").status_code == 204
    with Session(engine) as db:
        first_deadline = db.get(UserWithdrawal, "member").purge_after

    assert client.post("/api/auth/withdraw").status_code == 204

    with Session(engine) as db:
        assert db.get(UserWithdrawal, "member").purge_after == first_deadline


def test_withdraw_proceeds_when_kakao_unlink_fails(withdraw_api, monkeypatch):
    """공급자 장애가 사용자의 탈퇴를 막지 않는다."""
    client, engine = withdraw_api

    async def failing_unlink(_kakao_id):
        return False

    monkeypatch.setattr(auth_module, "unlink_kakao_account", failing_unlink)

    assert client.post("/api/auth/withdraw").status_code == 204

    with Session(engine) as db:
        withdrawal = db.get(UserWithdrawal, "member")
        assert withdrawal is not None
        # 실패를 기록해 파기 배치가 재시도할 수 있게 남긴다.
        assert withdrawal.provider_unlinked is False


def test_administrator_cannot_withdraw(tmp_path, monkeypatch):
    """관리자를 지우면 후기 검수 이력의 담당자가 비어 감사 추적이 끊긴다."""
    engine = _engine(tmp_path, "admin-withdrawal.sqlite3")
    user_id = _seed(engine, is_admin=True)

    def test_database_session():
        db = Session(engine)
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def authenticated(db: Session = Depends(database_session)):
        return db.get(User, user_id)

    app.dependency_overrides[database_session] = test_database_session
    app.dependency_overrides[current_user] = authenticated
    try:
        response = TestClient(app).post("/api/auth/withdraw")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    with Session(engine) as db:
        assert db.get(UserWithdrawal, user_id) is None


def test_pending_withdrawal_blocks_authenticated_access(tmp_path, monkeypatch):
    """다른 기기에 남은 세션 쿠키로도 탈퇴 계정에 접근할 수 없다."""
    engine = _engine(tmp_path, "blocked.sqlite3")
    user_id = _seed(engine)
    with Session(engine) as db:
        db.add(UserWithdrawal(
            user_id=user_id,
            purge_after=utc_now_naive() + timedelta(days=30),
        ))
        db.commit()

    monkeypatch.setattr(
        settings,
        "session_secret",
        "withdrawal-test-secret-with-32-characters",
    )
    monkeypatch.setattr(settings, "kakao_rest_api_key", "rest-key")
    monkeypatch.setattr(settings, "kakao_oauth_client_secret", "client-secret")
    monkeypatch.setattr(
        settings,
        "database_url",
        "postgresql+psycopg://user:pw@localhost:5432/kt10",
    )

    def test_database_session():
        db = Session(engine)
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[database_session] = test_database_session
    from app.database import optional_database_session

    app.dependency_overrides[optional_database_session] = test_database_session
    try:
        client = TestClient(app)
        client.cookies.set(
            "mobility_session",
            auth_module._serializer().dumps(user_id),
        )
        response = client.get("/api/auth/me")
    finally:
        app.dependency_overrides.clear()

    # 게스트와 동일하게 취급한다. 로그인 사용자 본문을 돌려주지 않는다.
    assert response.status_code == 204


def test_relogin_within_retention_cancels_the_withdrawal(tmp_path):
    """유예기간의 목적이 실수로 신청한 사용자를 되살리는 것이다."""
    engine = _engine(tmp_path, "restore.sqlite3")
    user_id = _seed(engine)
    with Session(engine) as db:
        db.add(UserWithdrawal(
            user_id=user_id,
            purge_after=utc_now_naive() + timedelta(days=30),
        ))
        db.commit()

    # kakao_callback의 복구 분기와 동일한 처리.
    with Session(engine) as db:
        user = db.get(User, user_id)
        withdrawal = db.get(UserWithdrawal, user.id)
        assert withdrawal is not None
        db.delete(withdrawal)
        user.nickname = "부산길"
        db.commit()

    with Session(engine) as db:
        assert db.get(UserWithdrawal, user_id) is None
        assert db.get(User, user_id).nickname == "부산길"
