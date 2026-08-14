"""Google Play 외부 계정 삭제 OAuth와 deletion credential 계약."""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.agreements import (
    AGREEMENT_ACTION_ACCEPTED,
    CURRENT_TERMS_VERSION,
    DOCUMENT_TYPE_TERMS,
)
from app.api import auth as auth_module
from app.api.auth import withdrawal_subject_hash
from app.database import (
    Base,
    FacilityReport,
    RouteImpression,
    RouteReview,
    User,
    UserAgreement,
    UserIdentity,
    UserPreference,
    UserWithdrawal,
    database_session,
    optional_database_session,
)
from app.main import app
from app.settings import settings

SECRET = "deletion-test-session-secret-32ch"
KAKAO_ID = "123456"
SALT = "withdrawal-test-salt-16plus"


def _engine(tmp_path, name):
    engine = create_engine(
        f"sqlite+pysqlite:///{(tmp_path / name).as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return engine


def _bind_db(engine):
    def test_database_session():
        db = Session(engine)
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def test_optional_database_session():
        db = Session(engine)
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[database_session] = test_database_session
    app.dependency_overrides[optional_database_session] = test_optional_database_session
    return TestClient(app, follow_redirects=False)


def _configure_auth(monkeypatch):
    monkeypatch.setattr(settings, "session_secret", SECRET)
    monkeypatch.setattr(settings, "frontend_url", "http://localhost:5173")
    monkeypatch.setattr(settings, "withdrawal_retention_days", 30)
    monkeypatch.setattr(settings, "withdrawal_hash_salt", SALT)
    monkeypatch.setattr(settings, "kakao_admin_key", "test-admin-key")
    monkeypatch.setattr(auth_module, "_configured", lambda: None)
    monkeypatch.setattr(auth_module, "_secure_cookie", lambda: False)


def _mock_kakao(monkeypatch, *, fail=False):
    def handler(request: httpx.Request) -> httpx.Response:
        if fail:
            return httpx.Response(502, request=request, text="provider down")
        if str(request.url).endswith("/oauth/token"):
            return httpx.Response(200, json={"access_token": "kakao-access"})
        if "/v2/user/me" in str(request.url):
            return httpx.Response(
                200,
                json={"id": int(KAKAO_ID), "properties": {"nickname": "부산길"}},
            )
        return httpx.Response(404, request=request)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        kwargs.setdefault("timeout", 5)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(auth_module.httpx, "AsyncClient", fake_client)


def _seed_user(engine, *, is_admin=False, with_agreement=True, nickname="이전"):
    with Session(engine) as db:
        user = User(id="member", kakao_id=KAKAO_ID, nickname=nickname, is_admin=is_admin)
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
        if with_agreement:
            db.add(UserAgreement(
                id="agreement-1",
                user_id=user.id,
                document_type=DOCUMENT_TYPE_TERMS,
                document_version=CURRENT_TERMS_VERSION,
                action=AGREEMENT_ACTION_ACCEPTED,
            ))
        db.commit()
    return "member"


def _start_deletion(client: TestClient):
    response = client.get("/api/auth/deletion/kakao/login")
    assert response.status_code == 307
    state = response.cookies[auth_module._STATE_COOKIE]
    return state


def _start_login(client: TestClient):
    response = client.get("/api/auth/kakao/login")
    assert response.status_code == 307
    return response.cookies[auth_module._STATE_COOKIE]


def _oauth_callback(client: TestClient, state: str):
    return client.get(
        "/api/auth/kakao/callback",
        params={"code": "auth-code", "state": state},
        cookies={auth_module._STATE_COOKIE: state},
    )


def _deletion_callback(client: TestClient, state: str):
    return _oauth_callback(client, state)


def _set_session_cookie(client: TestClient, user_id: str) -> None:
    client.cookies.set(
        auth_module._SESSION_COOKIE,
        auth_module._serializer().dumps(user_id),
    )


def _set_signup_cookie(client: TestClient, token: str) -> None:
    client.cookies.set(
        auth_module._SIGNUP_COOKIE,
        token,
        path=auth_module._SIGNUP_COOKIE_PATH,
    )


def _set_deletion_cookie(client: TestClient, token: str) -> None:
    client.cookies.set(
        auth_module._DELETION_COOKIE,
        token,
        path=auth_module._DELETION_COOKIE_PATH,
    )


def _deletion_token(user_id: str) -> str:
    return auth_module._deletion_credential_serializer().dumps({
        "kind": "existing",
        "user_id": user_id,
    })


def _cookie_cleared(response, name: str, *, path: str | None = None) -> bool:
    headers = response.headers.get_list("set-cookie")
    return any(
        header.startswith(f"{name}=")
        and ("Max-Age=0" in header or "max-age=0" in header.lower())
        and (path is None or f"Path={path}" in header)
        for header in headers
    )


def _live_cookie_value(response, name: str, *, path: str | None = None):
    for header in response.headers.get_list("set-cookie"):
        if not header.startswith(f"{name}="):
            continue
        if "Max-Age=0" in header or "max-age=0" in header.lower():
            continue
        if path is not None and f"Path={path}" not in header:
            continue
        return header.split(";", 1)[0].split("=", 1)[1]
    return None


def _deletion_cookie_from(response) -> str:
    token = _live_cookie_value(
        response,
        auth_module._DELETION_COOKIE,
        path=auth_module._DELETION_COOKIE_PATH,
    )
    assert token is not None
    return token


def _seed_other_user(engine, *, user_id="session-user", kakao_id="999999"):
    with Session(engine) as db:
        db.add(User(id=user_id, kakao_id=kakao_id, nickname="세션계정"))
        db.flush()
        db.add(UserPreference(user_id=user_id, profile="disabled"))
        db.commit()
    return user_id


@pytest.fixture()
def deletion_api(tmp_path, monkeypatch):
    engine = _engine(tmp_path, "deletion.sqlite3")
    _configure_auth(monkeypatch)
    _mock_kakao(monkeypatch)
    client = _bind_db(engine)
    try:
        yield client, engine
    finally:
        app.dependency_overrides.clear()


def test_deletion_login_creates_prefixed_state_not_session(deletion_api):
    client, _engine = deletion_api
    response = client.get("/api/auth/deletion/kakao/login")
    assert response.status_code == 307
    location = urlparse(response.headers["location"])
    assert location.netloc == "kauth.kakao.com"
    state = parse_qs(location.query)["state"][0]
    assert state.startswith(auth_module._DELETION_STATE_PREFIX)
    assert response.cookies[auth_module._STATE_COOKIE] == state
    assert auth_module._SESSION_COOKIE not in response.cookies
    assert auth_module._DELETION_COOKIE not in response.cookies
    assert auth_module._SIGNUP_COOKIE not in response.cookies


def test_normal_login_state_is_not_deletion_prefixed(deletion_api):
    client, _engine = deletion_api
    response = client.get("/api/auth/kakao/login")
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    assert not state.startswith(auth_module._DELETION_STATE_PREFIX)
    assert response.cookies[auth_module._STATE_COOKIE] == state


def test_tampered_deletion_state_is_400_not_login(deletion_api):
    client, engine = deletion_api
    _seed_user(engine)
    _start_deletion(client)
    tampered = f"{auth_module._DELETION_STATE_PREFIX}not-a-signature"
    response = client.get(
        "/api/auth/kakao/callback",
        params={"code": "auth-code", "state": tampered},
        cookies={auth_module._STATE_COOKIE: tampered},
    )
    assert response.status_code == 400
    with Session(engine) as db:
        assert db.get(User, "member") is not None
        assert db.get(User, "member").nickname == "이전"


def test_expired_deletion_oauth_state_is_400(deletion_api, monkeypatch):
    client, engine = deletion_api
    _seed_user(engine)
    state = _start_deletion(client)
    monkeypatch.setattr(auth_module, "_DELETION_MAX_AGE", -1)
    response = _deletion_callback(client, state)
    assert response.status_code == 400
    with Session(engine) as db:
        assert db.get(User, "member") is not None


def test_kakao_provider_failure_during_deletion_is_502(tmp_path, monkeypatch):
    engine = _engine(tmp_path, "deletion-fail.sqlite3")
    _configure_auth(monkeypatch)
    _mock_kakao(monkeypatch, fail=True)
    client = _bind_db(engine)
    try:
        _seed_user(engine)
        state = _start_deletion(client)
        response = _deletion_callback(client, state)
        assert response.status_code == 502
        with Session(engine) as db:
            assert db.get(User, "member") is not None
    finally:
        app.dependency_overrides.clear()


def test_existing_user_gets_deletion_credential_without_session(deletion_api):
    client, engine = deletion_api
    _seed_user(engine)
    state = _start_deletion(client)
    response = _deletion_callback(client, state)
    assert response.status_code == 307
    assert response.headers["location"] == "http://localhost:5173/account-deletion"
    assert auth_module._DELETION_COOKIE in response.cookies or _live_cookie_value(
        response,
        auth_module._DELETION_COOKIE,
        path=auth_module._DELETION_COOKIE_PATH,
    )
    assert _live_cookie_value(response, auth_module._SESSION_COOKIE) is None
    assert _cookie_cleared(response, auth_module._SESSION_COOKIE)
    assert _cookie_cleared(
        response,
        auth_module._SIGNUP_COOKIE,
        path=auth_module._SIGNUP_COOKIE_PATH,
    )
    assert any(
        header.startswith(f"{auth_module._DELETION_COOKIE}=")
        and "Path=/api/auth/deletion" in header
        and "HttpOnly" in header
        for header in response.headers.get_list("set-cookie")
    )
    with Session(engine) as db:
        user = db.get(User, "member")
        assert user.nickname == "이전"
        assert db.scalar(select(func.count()).select_from(UserAgreement)) == 1
        identities = list(db.scalars(select(UserIdentity)))
        assert len(identities) == 1
        assert identities[0].user_id == "member"
        assert identities[0].provider == "kakao"
        assert identities[0].provider_subject == KAKAO_ID


def test_legacy_user_without_agreement_does_not_go_to_signup(deletion_api):
    client, engine = deletion_api
    _seed_user(engine, with_agreement=False)
    state = _start_deletion(client)
    response = _deletion_callback(client, state)
    assert response.headers["location"] == "http://localhost:5173/account-deletion"
    assert "/signup/consent" not in response.headers["location"]
    assert auth_module._SESSION_COOKIE not in response.cookies
    assert auth_module._SIGNUP_COOKIE not in response.cookies
    with Session(engine) as db:
        assert db.scalar(select(UserAgreement)) is None
        assert db.get(User, "member").nickname == "이전"


def test_unknown_kakao_user_does_not_create_account(deletion_api):
    client, engine = deletion_api
    state = _start_deletion(client)
    response = _deletion_callback(client, state)
    assert response.status_code == 307
    assert "result=not-found" in response.headers["location"]
    assert _live_cookie_value(
        response,
        auth_module._DELETION_COOKIE,
        path=auth_module._DELETION_COOKIE_PATH,
    ) is None
    assert _cookie_cleared(
        response,
        auth_module._DELETION_COOKIE,
        path=auth_module._DELETION_COOKIE_PATH,
    )
    assert _live_cookie_value(response, auth_module._SESSION_COOKIE) is None
    assert _cookie_cleared(response, auth_module._SESSION_COOKIE)
    assert _cookie_cleared(
        response,
        auth_module._SIGNUP_COOKIE,
        path=auth_module._SIGNUP_COOKIE_PATH,
    )
    with Session(engine) as db:
        assert db.scalar(select(User)) is None
        assert db.scalar(select(UserPreference)) is None
        assert db.scalar(select(UserAgreement)) is None
        assert db.scalar(select(func.count()).select_from(UserIdentity)) == 0


def test_deletion_status_reports_verified_without_identity(deletion_api):
    client, engine = deletion_api
    _seed_user(engine)
    pending = _deletion_callback(client, _start_deletion(client))
    _set_deletion_cookie(client, _deletion_cookie_from(pending))
    response = client.get("/api/auth/deletion/status")
    assert response.status_code == 200
    assert response.json() == {"verified": True}
    assert "user_id" not in response.text
    assert KAKAO_ID not in response.text


def test_deletion_status_without_cookie_is_absent(deletion_api):
    client, _engine = deletion_api
    response = client.get("/api/auth/deletion/status")
    assert response.status_code == 204


def test_deletion_status_normalizes_invalid_cookie(deletion_api):
    client, _engine = deletion_api
    _set_deletion_cookie(client, "not-a-signed-value")
    response = client.get("/api/auth/deletion/status")
    assert response.status_code == 204


def test_confirm_deletes_account_with_existing_policy(deletion_api, monkeypatch):
    client, engine = deletion_api
    unlinked = []

    async def fake_unlink(kakao_id):
        unlinked.append(kakao_id)
        return True

    monkeypatch.setattr(auth_module, "unlink_kakao_account", fake_unlink)
    _seed_user(engine)
    pending = _deletion_callback(client, _start_deletion(client))
    token = _deletion_cookie_from(pending)
    _set_deletion_cookie(client, token)
    response = client.post("/api/auth/deletion/confirm")
    assert response.status_code == 204
    assert unlinked == [KAKAO_ID]
    assert _cookie_cleared(
        response,
        auth_module._DELETION_COOKIE,
        path=auth_module._DELETION_COOKIE_PATH,
    )
    assert "mobility_session" in response.headers.get("set-cookie", "").lower() or _cookie_cleared(
        response, auth_module._SESSION_COOKIE,
    )
    with Session(engine) as db:
        assert db.get(User, "member") is None
        assert db.get(UserPreference, "member") is None
        assert db.get(UserAgreement, "agreement-1") is None
        assert db.get(RouteReview, "review-1") is None
        assert db.get(RouteImpression, "impression-1") is None
        report = db.get(FacilityReport, "report-1")
        assert report is not None
        assert report.user_id is None
        assert report.description is None
        assert report.reported_lat is None
        assert report.reported_lng is None
        assert report.facility_name == "부산역 1번 승강기"
        record = db.scalar(select(UserWithdrawal))
        assert record is not None
        assert record.user_ref == "member"
        assert record.status == "completed"
        assert record.pending_provider_id is None
        assert record.subject_hash == withdrawal_subject_hash(KAKAO_ID)
        assert db.scalar(select(func.count()).select_from(UserIdentity)) == 0


def test_confirm_replay_does_not_reissue_or_recreate(deletion_api, monkeypatch):
    client, engine = deletion_api

    async def fake_unlink(_kakao_id):
        return True

    monkeypatch.setattr(auth_module, "unlink_kakao_account", fake_unlink)
    _seed_user(engine)
    pending = _deletion_callback(client, _start_deletion(client))
    token = _deletion_cookie_from(pending)
    _set_deletion_cookie(client, token)
    first = client.post("/api/auth/deletion/confirm")
    assert first.status_code == 204
    _set_deletion_cookie(client, token)
    second = client.post("/api/auth/deletion/confirm")
    assert second.status_code == 410
    assert auth_module._SESSION_COOKIE not in second.cookies
    assert _cookie_cleared(
        second,
        auth_module._DELETION_COOKIE,
        path=auth_module._DELETION_COOKIE_PATH,
    )
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 0
        assert db.scalar(select(func.count()).select_from(UserPreference)) == 0
        assert db.scalar(select(func.count()).select_from(UserAgreement)) == 0
        assert db.scalar(select(func.count()).select_from(UserWithdrawal)) == 1


def test_admin_confirm_is_409_and_does_not_unlink(deletion_api, monkeypatch):
    client, engine = deletion_api
    calls = []

    async def fake_unlink(kakao_id):
        calls.append(kakao_id)
        return True

    monkeypatch.setattr(auth_module, "unlink_kakao_account", fake_unlink)
    _seed_user(engine, is_admin=True)
    pending = _deletion_callback(client, _start_deletion(client))
    _set_deletion_cookie(client, _deletion_cookie_from(pending))
    response = client.post("/api/auth/deletion/confirm")
    assert response.status_code == 409
    assert calls == []
    with Session(engine) as db:
        assert db.get(User, "member") is not None
        assert db.scalar(select(UserWithdrawal)) is None


def test_failed_unlink_keeps_provider_id(deletion_api, monkeypatch):
    client, engine = deletion_api

    async def failing_unlink(_kakao_id):
        return False

    monkeypatch.setattr(auth_module, "unlink_kakao_account", failing_unlink)
    _seed_user(engine)
    pending = _deletion_callback(client, _start_deletion(client))
    _set_deletion_cookie(client, _deletion_cookie_from(pending))
    assert client.post("/api/auth/deletion/confirm").status_code == 204
    with Session(engine) as db:
        assert db.get(User, "member") is None
        record = db.scalar(select(UserWithdrawal))
        assert record.status == "provider_unlink_pending"
        assert record.pending_provider_id == KAKAO_ID


def test_cancel_clears_credential_and_keeps_user(deletion_api):
    client, engine = deletion_api
    _seed_user(engine)
    pending = _deletion_callback(client, _start_deletion(client))
    _set_deletion_cookie(client, _deletion_cookie_from(pending))
    response = client.post("/api/auth/deletion/cancel")
    assert response.status_code == 204
    assert _cookie_cleared(
        response,
        auth_module._DELETION_COOKIE,
        path=auth_module._DELETION_COOKIE_PATH,
    )
    with Session(engine) as db:
        assert db.get(User, "member") is not None
        assert db.scalar(select(UserWithdrawal)) is None


def test_confirm_without_cookie_is_401(deletion_api):
    client, engine = deletion_api
    _seed_user(engine)
    response = client.post("/api/auth/deletion/confirm")
    assert response.status_code == 401
    with Session(engine) as db:
        assert db.get(User, "member") is not None


def test_deletion_oauth_clears_session_a_and_issues_credential_b(deletion_api):
    client, engine = deletion_api
    session_user = _seed_other_user(engine)
    _seed_user(engine)
    _set_session_cookie(client, session_user)
    _set_signup_cookie(
        client,
        auth_module._signup_serializer().dumps({
            "kind": "existing",
            "user_id": session_user,
        }),
    )
    _set_deletion_cookie(client, _deletion_token(session_user))
    response = _deletion_callback(client, _start_deletion(client))
    assert response.status_code == 307
    assert response.headers["location"] == "http://localhost:5173/account-deletion"
    assert _cookie_cleared(response, auth_module._SESSION_COOKIE)
    assert _live_cookie_value(response, auth_module._SESSION_COOKIE) is None
    assert _cookie_cleared(
        response,
        auth_module._SIGNUP_COOKIE,
        path=auth_module._SIGNUP_COOKIE_PATH,
    )
    token = _deletion_cookie_from(response)
    payload = auth_module._deletion_credential_serializer().loads(
        token,
        max_age=auth_module._DELETION_MAX_AGE,
    )
    assert payload == {"kind": "existing", "user_id": "member"}
    with Session(engine) as db:
        assert db.get(User, session_user) is not None
        assert db.get(User, "member") is not None


def test_unknown_deletion_oauth_clears_session_without_credential(deletion_api):
    client, engine = deletion_api
    session_user = _seed_other_user(engine)
    _set_session_cookie(client, session_user)
    _set_signup_cookie(
        client,
        auth_module._signup_serializer().dumps({
            "kind": "existing",
            "user_id": session_user,
        }),
    )
    _set_deletion_cookie(client, _deletion_token(session_user))
    response = _deletion_callback(client, _start_deletion(client))
    assert response.status_code == 307
    assert "result=not-found" in response.headers["location"]
    assert _cookie_cleared(response, auth_module._SESSION_COOKIE)
    assert _live_cookie_value(response, auth_module._SESSION_COOKIE) is None
    assert _live_cookie_value(
        response,
        auth_module._DELETION_COOKIE,
        path=auth_module._DELETION_COOKIE_PATH,
    ) is None
    assert _cookie_cleared(
        response,
        auth_module._DELETION_COOKIE,
        path=auth_module._DELETION_COOKIE_PATH,
    )
    assert _cookie_cleared(
        response,
        auth_module._SIGNUP_COOKIE,
        path=auth_module._SIGNUP_COOKIE_PATH,
    )
    with Session(engine) as db:
        assert db.get(User, session_user) is not None
        assert db.scalar(select(func.count()).select_from(User)) == 1


def test_normal_login_clears_stale_deletion_credential(deletion_api):
    client, engine = deletion_api
    _seed_user(engine)
    other = _seed_other_user(engine, user_id="other", kakao_id="888888")
    _set_deletion_cookie(client, _deletion_token(other))
    response = _oauth_callback(client, _start_login(client))
    assert response.status_code == 307
    assert response.headers["location"] == "http://localhost:5173/"
    assert _cookie_cleared(
        response,
        auth_module._DELETION_COOKIE,
        path=auth_module._DELETION_COOKIE_PATH,
    )
    session = _live_cookie_value(response, auth_module._SESSION_COOKIE)
    assert session is not None
    assert auth_module._serializer().loads(session, max_age=60 * 60 * 24 * 14) == "member"


def test_signup_pending_clears_stale_deletion_credential(deletion_api):
    client, engine = deletion_api
    _seed_user(engine, with_agreement=False)
    _set_deletion_cookie(client, _deletion_token("member"))
    response = _oauth_callback(client, _start_login(client))
    assert response.status_code == 307
    assert response.headers["location"] == "http://localhost:5173/signup/consent"
    assert _cookie_cleared(
        response,
        auth_module._DELETION_COOKIE,
        path=auth_module._DELETION_COOKIE_PATH,
    )
    assert _live_cookie_value(
        response,
        auth_module._SIGNUP_COOKIE,
        path=auth_module._SIGNUP_COOKIE_PATH,
    ) is not None
    assert _live_cookie_value(response, auth_module._SESSION_COOKIE) is None


def test_new_user_signup_pending_clears_stale_deletion_credential(deletion_api):
    client, engine = deletion_api
    _set_deletion_cookie(client, _deletion_token("stale-user"))
    response = _oauth_callback(client, _start_login(client))
    assert response.status_code == 307
    assert response.headers["location"] == "http://localhost:5173/signup/consent"
    assert _cookie_cleared(
        response,
        auth_module._DELETION_COOKIE,
        path=auth_module._DELETION_COOKIE_PATH,
    )
    assert _live_cookie_value(
        response,
        auth_module._SIGNUP_COOKIE,
        path=auth_module._SIGNUP_COOKIE_PATH,
    ) is not None
    with Session(engine) as db:
        assert db.scalar(select(User)) is None


def test_signup_complete_clears_stale_deletion_credential(deletion_api):
    client, engine = deletion_api
    pending = _oauth_callback(client, _start_login(client))
    signup_token = _live_cookie_value(
        pending,
        auth_module._SIGNUP_COOKIE,
        path=auth_module._SIGNUP_COOKIE_PATH,
    )
    assert signup_token is not None
    _set_signup_cookie(client, signup_token)
    _set_deletion_cookie(client, _deletion_token("stale-user"))
    response = client.post("/api/auth/signup/complete", json={"acceptTerms": True})
    assert response.status_code == 204
    assert _cookie_cleared(
        response,
        auth_module._DELETION_COOKIE,
        path=auth_module._DELETION_COOKIE_PATH,
    )
    assert _live_cookie_value(response, auth_module._SESSION_COOKIE) is not None
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1
