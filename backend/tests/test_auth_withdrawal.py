"""회원 탈퇴의 즉시 삭제와 최소 정보 분리 보관 계약.

계정·프로필·서비스 데이터는 탈퇴 시점에 사라진다. 남는 것은 부정 가입·탈퇴
반복 방지와 처리 오류 대응에 필요한 최소 정보뿐이어야 한다.
"""
from __future__ import annotations

import json

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.api import auth as auth_module
from app.api.auth import current_user, withdrawal_subject_hash
from app.database import (
    Base,
    FacilityReport,
    RouteImpression,
    RouteReview,
    User,
    UserAgreement,
    UserPreference,
    UserWithdrawal,
    database_session,
)
from app.main import app
from app.settings import settings

SALT = "withdrawal-test-salt-16plus"


def _engine(tmp_path, name):
    engine = create_engine(
        f"sqlite+pysqlite:///{(tmp_path / name).as_posix()}",
        connect_args={"check_same_thread": False},
    )

    # 즉시 삭제가 CASCADE·SET NULL에 의존하므로 SQLite에서도 외래키를 켠다.
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return engine


def _seed(engine, *, is_admin=False):
    with Session(engine) as db:
        user = User(id="member", kakao_id="7001", nickname="부산길", is_admin=is_admin)
        db.add(user)
        db.flush()
        db.add(UserPreference(user_id=user.id, profile="disabled"))
        impression = RouteImpression(
            id="impression-1",
            user_id=user.id,
            route_id="route-1",
            profile="disabled",
            rank=1,
            feature_snapshot=json.dumps({"avg_slope_percent": 3.1}),
        )
        db.add(impression)
        db.flush()
        db.add(RouteReview(
            id="review-1",
            user_id=user.id,
            impression_id=impression.id,
            route_id="route-1",
            was_usable=True,
            rating=4,
            comment="계단이 많았습니다.",
        ))
        db.add(FacilityReport(
            id="report-1",
            user_id=user.id,
            facility_name="부산역 1번 승강기",
            facility_type="elevator",
            issue_type="broken",
            reported_lat=35.1151,
            reported_lng=129.0414,
            description="승강기가 고장났습니다.",
            resolution_note="현장 확인 예정",
        ))
        db.add(UserAgreement(
            id="agreement-1",
            user_id=user.id,
            document_type="terms",
            document_version="v1",
            action="accepted",
        ))
        db.commit()
    return "member"


def _client(engine, user_id):
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
    return TestClient(app)


@pytest.fixture()
def withdraw_api(tmp_path, monkeypatch):
    engine = _engine(tmp_path, "withdrawal.sqlite3")
    user_id = _seed(engine)
    monkeypatch.setattr(settings, "withdrawal_retention_days", 30)
    monkeypatch.setattr(settings, "withdrawal_hash_salt", SALT)
    monkeypatch.setattr(settings, "kakao_admin_key", "test-admin-key")

    async def fake_unlink(_kakao_id):
        return True

    monkeypatch.setattr(auth_module, "unlink_kakao_account", fake_unlink)
    try:
        yield _client(engine, user_id), engine
    finally:
        app.dependency_overrides.clear()


def test_withdraw_deletes_account_and_service_data_immediately(withdraw_api):
    client, engine = withdraw_api

    assert client.post("/api/auth/withdraw").status_code == 204

    with Session(engine) as db:
        # 계정과 프로필은 보관기간을 기다리지 않고 사라진다.
        assert db.get(User, "member") is None
        assert db.get(UserPreference, "member") is None
        # 후기는 개인이 작성한 글이라 함께 삭제한다.
        assert db.get(RouteReview, "review-1") is None
        # 이용약관 수락 기록도 계정 CASCADE로 함께 삭제한다.
        assert db.get(UserAgreement, "agreement-1") is None


def test_route_impressions_are_deleted_not_just_detached(withdraw_api):
    """profile과 feature_snapshot이 남으면 익명화됐다고 볼 수 없다."""
    client, engine = withdraw_api

    assert client.post("/api/auth/withdraw").status_code == 204

    with Session(engine) as db:
        assert db.get(RouteImpression, "impression-1") is None


def test_facility_report_keeps_only_facility_identifying_fields(withdraw_api):
    """시설 식별·유지보수에 필요한 정보만 남기고 개인 식별 여지를 지운다."""
    client, engine = withdraw_api

    assert client.post("/api/auth/withdraw").status_code == 204

    with Session(engine) as db:
        report = db.get(FacilityReport, "report-1")
        assert report is not None
        # 작성자 연결, 자유입력, 신고 시점 사용자 GPS는 지운다.
        assert report.user_id is None
        assert report.description is None
        assert report.reported_lat is None
        assert report.reported_lng is None
        # 시설 자체를 식별·관리하는 정보와 관리자 메모는 보존한다.
        assert report.facility_name == "부산역 1번 승강기"
        assert report.facility_type == "elevator"
        assert report.issue_type == "broken"
        assert report.status == "pending"
        assert report.resolution_note == "현장 확인 예정"


def test_withdrawal_record_keeps_only_minimal_fields(withdraw_api):
    client, engine = withdraw_api

    assert client.post("/api/auth/withdraw").status_code == 204

    with Session(engine) as db:
        record = db.scalar(select(UserWithdrawal))
        assert record is not None
        assert record.user_ref == "member"
        assert record.status == "completed"
        # 연결 끊기에 성공했으면 회원번호를 남기지 않는다.
        assert record.pending_provider_id is None
        # 회원번호 원문이 아니라 salt 해시만 남는다.
        assert record.subject_hash == withdrawal_subject_hash("7001")
        assert "7001" not in (record.subject_hash or "")


def test_repeat_withdrawal_is_detectable_by_subject_hash(withdraw_api):
    """같은 사람이 다시 가입해 탈퇴하면 같은 해시가 나와야 판별할 수 있다."""
    client, engine = withdraw_api
    assert client.post("/api/auth/withdraw").status_code == 204

    # 같은 카카오 회원번호로 재가입한 뒤 다시 탈퇴.
    with Session(engine) as db:
        db.add(User(id="member2", kakao_id="7001", nickname="부산길"))
        db.commit()
    app.dependency_overrides.clear()
    client2 = _client(engine, "member2")
    assert client2.post("/api/auth/withdraw").status_code == 204

    with Session(engine) as db:
        hashes = list(db.scalars(select(UserWithdrawal.subject_hash)))
        assert len(hashes) == 2
        assert hashes[0] == hashes[1]


def test_subject_hash_is_omitted_without_a_salt(withdraw_api, monkeypatch):
    """역산 가능한 약한 해시를 안전한 척 남기지 않는다."""
    client, engine = withdraw_api
    monkeypatch.setattr(settings, "withdrawal_hash_salt", "")

    assert client.post("/api/auth/withdraw").status_code == 204

    with Session(engine) as db:
        assert db.scalar(select(UserWithdrawal)).subject_hash is None


def test_failed_unlink_keeps_provider_id_for_retry(withdraw_api, monkeypatch):
    """공급자 장애가 탈퇴를 막지 않되, 재시도할 근거는 남긴다."""
    client, engine = withdraw_api

    async def failing_unlink(_kakao_id):
        return False

    monkeypatch.setattr(auth_module, "unlink_kakao_account", failing_unlink)

    assert client.post("/api/auth/withdraw").status_code == 204

    with Session(engine) as db:
        # 삭제는 예정대로 끝난다.
        assert db.get(User, "member") is None
        record = db.scalar(select(UserWithdrawal))
        assert record.status == "provider_unlink_pending"
        assert record.pending_provider_id == "7001"


def test_withdraw_clears_session_cookie(withdraw_api):
    client, _ = withdraw_api

    response = client.post("/api/auth/withdraw")

    assert response.status_code == 204
    assert "mobility_session" in response.headers.get("set-cookie", "")


def test_administrator_cannot_withdraw(tmp_path):
    """관리자를 지우면 후기 검수 이력의 담당자가 비어 감사 추적이 끊긴다."""
    engine = _engine(tmp_path, "admin-withdrawal.sqlite3")
    user_id = _seed(engine, is_admin=True)
    try:
        response = _client(engine, user_id).post("/api/auth/withdraw")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    with Session(engine) as db:
        assert db.get(User, user_id) is not None
        assert db.scalar(select(UserWithdrawal)) is None


def test_relogin_after_withdrawal_creates_a_new_account(tmp_path, monkeypatch):
    """재로그인이 탈퇴를 자동 철회하지 않는다. 새 계정으로 가입될 뿐이다."""
    engine = _engine(tmp_path, "relogin.sqlite3")
    user_id = _seed(engine)
    monkeypatch.setattr(settings, "withdrawal_hash_salt", SALT)

    async def fake_unlink(_kakao_id):
        return True

    monkeypatch.setattr(auth_module, "unlink_kakao_account", fake_unlink)
    try:
        assert _client(engine, user_id).post("/api/auth/withdraw").status_code == 204
    finally:
        app.dependency_overrides.clear()

    # kakao_callback의 신규 가입 분기와 동일한 처리.
    with Session(engine) as db:
        assert db.scalar(select(User).where(User.kakao_id == "7001")) is None
        fresh = User(kakao_id="7001", nickname="부산길")
        db.add(fresh)
        db.flush()
        db.add(UserPreference(user_id=fresh.id))
        db.commit()
        # 새 계정은 이전 설정을 물려받지 않는다.
        assert fresh.id != user_id
        assert db.get(UserPreference, fresh.id).profile == "general"
        # 탈퇴 기록은 보관기간 동안 그대로 남는다.
        assert db.scalar(select(UserWithdrawal)) is not None
