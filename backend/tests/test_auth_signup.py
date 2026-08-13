"""Kakao 신규/기존 가입의 이용약관 수락 계약."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.agreements import (
    AGREEMENT_ACTION_ACCEPTED,
    CURRENT_TERMS_VERSION,
    DOCUMENT_TYPE_TERMS,
    consume_current_terms_agreement,
    has_current_terms_agreement,
)
from app.api import auth as auth_module
from app.database import (
    Base,
    User,
    UserAgreement,
    UserPreference,
    database_session,
    optional_database_session,
)
from app.main import app
from app.settings import settings

SECRET = "signup-test-session-secret-32chars"
STATE = "oauth-state-token-for-tests"
KAKAO_ID = "123456"


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


def _callback(client: TestClient, *, state=STATE, error=None, code="auth-code"):
    params = {"state": state}
    if code is not None:
        params["code"] = code
    if error is not None:
        params["error"] = error
    return client.get(
        "/api/auth/kakao/callback",
        params=params,
        cookies={auth_module._STATE_COOKIE: STATE},
    )


def _set_pending_cookie(client: TestClient, token: str) -> None:
    client.cookies.set(
        auth_module._SIGNUP_COOKIE,
        token,
        path=auth_module._SIGNUP_COOKIE_PATH,
    )


def _cookie_cleared(response, name: str) -> bool:
    headers = response.headers.get_list("set-cookie")
    return any(
        header.startswith(f"{name}=")
        and ("Max-Age=0" in header or "max-age=0" in header.lower())
        and (
            name != auth_module._SIGNUP_COOKIE
            or f"Path={auth_module._SIGNUP_COOKIE_PATH}" in header
        )
        for header in headers
    )


@pytest.fixture()
def signup_api(tmp_path, monkeypatch):
    engine = _engine(tmp_path, "signup.sqlite3")
    _configure_auth(monkeypatch)
    _mock_kakao(monkeypatch)
    client = _bind_db(engine)
    try:
        yield client, engine
    finally:
        app.dependency_overrides.clear()


def test_new_kakao_callback_does_not_create_account(signup_api):
    client, engine = signup_api

    response = _callback(client)

    assert response.status_code == 307
    assert response.headers["location"] == "http://localhost:5173/signup/consent"
    assert auth_module._SIGNUP_COOKIE in response.cookies
    assert auth_module._SESSION_COOKIE not in response.cookies
    assert any(
        header.startswith(f"{auth_module._SIGNUP_COOKIE}=")
        and "Path=/api/auth/signup" in header
        for header in response.headers.get_list("set-cookie")
    )
    with Session(engine) as db:
        assert db.scalar(select(User)) is None
        assert db.scalar(select(UserPreference)) is None
        assert db.scalar(select(UserAgreement)) is None


def test_existing_user_with_current_terms_gets_session(signup_api):
    client, engine = signup_api
    with Session(engine) as db:
        user = User(id="member", kakao_id=KAKAO_ID, nickname="이전")
        db.add(user)
        db.flush()
        db.add(UserPreference(user_id=user.id))
        db.add(UserAgreement(
            user_id=user.id,
            document_type=DOCUMENT_TYPE_TERMS,
            document_version=CURRENT_TERMS_VERSION,
            action=AGREEMENT_ACTION_ACCEPTED,
        ))
        db.commit()

    response = _callback(client)

    assert response.status_code == 307
    assert response.headers["location"] == "http://localhost:5173/"
    assert auth_module._SESSION_COOKIE in response.cookies
    with Session(engine) as db:
        assert db.get(User, "member").nickname == "부산길"


def test_legacy_user_without_agreement_goes_to_consent(signup_api):
    client, engine = signup_api
    with Session(engine) as db:
        user = User(id="legacy", kakao_id=KAKAO_ID, nickname="이전")
        db.add(user)
        db.flush()
        db.add(UserPreference(user_id=user.id))
        db.commit()

    response = _callback(client)

    assert response.status_code == 307
    assert response.headers["location"] == "http://localhost:5173/signup/consent"
    assert auth_module._SIGNUP_COOKIE in response.cookies
    assert auth_module._SESSION_COOKIE not in response.cookies
    with Session(engine) as db:
        assert db.scalar(select(User)) is not None
        assert db.scalar(select(UserAgreement)) is None


def test_old_terms_version_is_not_current_agreement(signup_api):
    client, engine = signup_api
    with Session(engine) as db:
        user = User(id="oldver", kakao_id=KAKAO_ID, nickname="이전")
        db.add(user)
        db.flush()
        db.add(UserPreference(user_id=user.id))
        db.add(UserAgreement(
            user_id=user.id,
            document_type=DOCUMENT_TYPE_TERMS,
            document_version="v0",
            action=AGREEMENT_ACTION_ACCEPTED,
        ))
        db.commit()
        assert has_current_terms_agreement(db, user) is False

    response = _callback(client)
    assert response.headers["location"] == "http://localhost:5173/signup/consent"
    assert auth_module._SESSION_COOKIE not in response.cookies


def test_signup_complete_creates_new_user_and_session(signup_api):
    client, engine = signup_api
    pending = _callback(client)
    _set_pending_cookie(client, pending.cookies[auth_module._SIGNUP_COOKIE])

    response = client.post("/api/auth/signup/complete", json={"acceptTerms": True})

    assert response.status_code == 204
    assert auth_module._SESSION_COOKIE in response.cookies
    assert _cookie_cleared(response, auth_module._SIGNUP_COOKIE)
    with Session(engine) as db:
        users = list(db.scalars(select(User)))
        assert len(users) == 1
        assert users[0].kakao_id == KAKAO_ID
        assert users[0].nickname == "부산길"
        assert db.get(UserPreference, users[0].id) is not None
        agreements = list(db.scalars(select(UserAgreement)))
        assert len(agreements) == 1
        assert agreements[0].document_type == DOCUMENT_TYPE_TERMS
        assert agreements[0].document_version == CURRENT_TERMS_VERSION
        assert agreements[0].action == AGREEMENT_ACTION_ACCEPTED


def test_signup_complete_rejects_missing_acceptance(signup_api):
    client, engine = signup_api
    pending = _callback(client)
    _set_pending_cookie(client, pending.cookies[auth_module._SIGNUP_COOKIE])

    response = client.post("/api/auth/signup/complete", json={"acceptTerms": False})

    assert response.status_code == 400
    assert auth_module._SESSION_COOKIE not in response.cookies
    with Session(engine) as db:
        assert db.scalar(select(User)) is None
        assert db.scalar(select(UserAgreement)) is None


def test_signup_complete_rejects_invalid_cookie(signup_api):
    client, engine = signup_api
    _set_pending_cookie(client, "not-a-signed-value")

    response = client.post("/api/auth/signup/complete", json={"acceptTerms": True})

    assert response.status_code == 401
    with Session(engine) as db:
        assert db.scalar(select(User)) is None


def test_signup_complete_rejects_expired_cookie(signup_api, monkeypatch):
    client, engine = signup_api
    pending = _callback(client)
    token = pending.cookies[auth_module._SIGNUP_COOKIE]
    monkeypatch.setattr(auth_module, "_SIGNUP_MAX_AGE", -1)
    _set_pending_cookie(client, token)
    response = client.post("/api/auth/signup/complete", json={"acceptTerms": True})
    assert response.status_code == 410
    with Session(engine) as db:
        assert db.scalar(select(User)) is None


def test_signup_complete_existing_legacy_user(signup_api):
    client, engine = signup_api
    with Session(engine) as db:
        user = User(id="legacy", kakao_id=KAKAO_ID, nickname="이전")
        db.add(user)
        db.flush()
        db.add(UserPreference(user_id=user.id, profile="disabled"))
        db.commit()
    pending = _callback(client)
    _set_pending_cookie(client, pending.cookies[auth_module._SIGNUP_COOKIE])

    response = client.post("/api/auth/signup/complete", json={"acceptTerms": True})

    assert response.status_code == 204
    assert auth_module._SESSION_COOKIE in response.cookies
    with Session(engine) as db:
        users = list(db.scalars(select(User)))
        assert len(users) == 1
        assert users[0].id == "legacy"
        assert db.get(UserPreference, "legacy").profile == "disabled"
        assert db.scalar(select(UserAgreement).where(UserAgreement.user_id == "legacy")) is not None


def test_signup_complete_rejects_replayed_pending_credential(signup_api):
    client, engine = signup_api
    pending = _callback(client)
    token = pending.cookies[auth_module._SIGNUP_COOKIE]
    _set_pending_cookie(client, token)
    first = client.post("/api/auth/signup/complete", json={"acceptTerms": True})
    assert first.status_code == 204
    assert auth_module._SESSION_COOKIE in first.cookies
    assert not any(
        header.startswith(f"{auth_module._SESSION_COOKIE}=")
        and f"Path={auth_module._SIGNUP_COOKIE_PATH}" in header
        for header in first.headers.get_list("set-cookie")
    )
    _set_pending_cookie(client, token)
    second = client.post("/api/auth/signup/complete", json={"acceptTerms": True})
    assert second.status_code == 409
    assert not any(
        header.startswith(f"{auth_module._SESSION_COOKIE}=")
        for header in second.headers.get_list("set-cookie")
    )
    assert _cookie_cleared(second, auth_module._SIGNUP_COOKIE)
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1
        assert db.scalar(select(func.count()).select_from(UserAgreement)) == 1
        assert db.scalar(select(func.count()).select_from(UserPreference)) == 1


def test_legacy_pending_token_replay_does_not_reissue_session(signup_api):
    client, engine = signup_api
    with Session(engine) as db:
        user = User(id="legacy", kakao_id=KAKAO_ID, nickname="이전")
        db.add(user)
        db.flush()
        db.add(UserPreference(user_id=user.id, profile="disabled"))
        db.commit()
    pending = _callback(client)
    token = pending.cookies[auth_module._SIGNUP_COOKIE]
    _set_pending_cookie(client, token)
    first = client.post("/api/auth/signup/complete", json={"acceptTerms": True})
    assert first.status_code == 204
    assert auth_module._SESSION_COOKIE in first.cookies
    assert not any(
        header.startswith(f"{auth_module._SESSION_COOKIE}=")
        and f"Path={auth_module._SIGNUP_COOKIE_PATH}" in header
        for header in first.headers.get_list("set-cookie")
    )
    _set_pending_cookie(client, token)
    second = client.post("/api/auth/signup/complete", json={"acceptTerms": True})
    assert second.status_code == 409
    assert not any(
        header.startswith(f"{auth_module._SESSION_COOKIE}=")
        for header in second.headers.get_list("set-cookie")
    )
    assert _cookie_cleared(second, auth_module._SIGNUP_COOKIE)
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1
        assert db.get(User, "legacy") is not None
        assert db.scalar(select(func.count()).select_from(UserAgreement)) == 1
        assert db.scalar(select(func.count()).select_from(UserPreference)) == 1


def test_signup_cancel_does_not_create_account(signup_api):
    client, engine = signup_api
    pending = _callback(client)
    _set_pending_cookie(client, pending.cookies[auth_module._SIGNUP_COOKIE])

    response = client.post("/api/auth/signup/cancel")

    assert response.status_code == 204
    assert _cookie_cleared(response, auth_module._SIGNUP_COOKIE)
    with Session(engine) as db:
        assert db.scalar(select(User)) is None
        assert db.scalar(select(UserAgreement)) is None


def test_signup_status_reports_pending_without_identity(signup_api):
    client, _engine = signup_api
    pending = _callback(client)
    _set_pending_cookie(client, pending.cookies[auth_module._SIGNUP_COOKIE])

    response = client.get("/api/auth/signup/status")

    assert response.status_code == 200
    assert response.json() == {"pending": True}


def test_signup_status_without_cookie_is_guest(signup_api):
    client, _engine = signup_api
    response = client.get("/api/auth/signup/status")
    assert response.status_code == 204


def test_me_stays_guest_while_signup_is_pending(signup_api):
    client, _engine = signup_api
    pending = _callback(client)
    _set_pending_cookie(client, pending.cookies[auth_module._SIGNUP_COOKIE])
    response = client.get("/api/auth/me")
    assert response.status_code == 204


def test_oauth_state_failure_creates_nothing(signup_api):
    client, engine = signup_api
    response = _callback(client, state="wrong-state")
    assert response.status_code == 400
    with Session(engine) as db:
        assert db.scalar(select(User)) is None
        assert db.scalar(select(UserAgreement)) is None


def test_kakao_provider_failure_creates_nothing(tmp_path, monkeypatch):
    engine = _engine(tmp_path, "provider-fail.sqlite3")
    _configure_auth(monkeypatch)
    _mock_kakao(monkeypatch, fail=True)
    client = _bind_db(engine)
    try:
        response = _callback(client)
        assert response.status_code == 502
        with Session(engine) as db:
            assert db.scalar(select(User)) is None
    finally:
        app.dependency_overrides.clear()


def test_complete_existing_user_gone_does_not_create_account(signup_api):
    client, engine = signup_api
    with Session(engine) as db:
        user = User(id="legacy", kakao_id=KAKAO_ID, nickname="이전")
        db.add(user)
        db.flush()
        db.add(UserPreference(user_id=user.id))
        db.commit()
    pending = _callback(client)
    token = pending.cookies[auth_module._SIGNUP_COOKIE]
    with Session(engine) as db:
        db.delete(db.get(User, "legacy"))
        db.commit()
    _set_pending_cookie(client, token)
    response = client.post("/api/auth/signup/complete", json={"acceptTerms": True})
    assert response.status_code == 401
    with Session(engine) as db:
        assert db.scalar(select(User)) is None


def test_client_cannot_choose_document_version(signup_api):
    client, engine = signup_api
    pending = _callback(client)
    _set_pending_cookie(client, pending.cookies[auth_module._SIGNUP_COOKIE])
    response = client.post(
        "/api/auth/signup/complete",
        json={"acceptTerms": True, "documentVersion": "v99", "kakaoId": "999"},
    )
    assert response.status_code == 204
    with Session(engine) as db:
        agreement = db.scalar(select(UserAgreement))
        assert agreement.document_version == CURRENT_TERMS_VERSION
        assert db.scalar(select(User)).kakao_id == KAKAO_ID


def test_consume_current_terms_agreement_is_false_when_already_accepted(signup_api):
    _client, engine = signup_api
    with Session(engine) as db:
        user = User(id="member", kakao_id=KAKAO_ID, nickname="이전")
        db.add(user)
        db.flush()
        db.add(UserPreference(user_id=user.id))
        db.commit()
        assert consume_current_terms_agreement(db, user) is True
        db.commit()
        assert consume_current_terms_agreement(db, user) is False
        db.commit()
        assert db.scalar(select(func.count()).select_from(UserAgreement)) == 1


def test_migration_revision_chain_points_at_current_head():
    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    text = (versions / "20260813_0008_user_agreements.py").read_text(encoding="utf-8")
    assert 'revision: str = "20260813_0008"' in text
    assert "20260812_0007" in text
    assert "user_agreements" in text
    assert "op.drop_table" in text
    assert "INSERT INTO" not in text.upper()
