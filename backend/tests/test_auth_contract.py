"""Kakao 인증 공급자 응답과 운영 쿠키 보안 계약."""

import pytest

from app.api.auth import _provider_identity, _secure_cookie
from app.settings import settings


def test_kakao_provider_identity_accepts_numeric_id_and_optional_nickname():
    assert _provider_identity({
        "id": 123456,
        "properties": {"nickname": "부산길"},
    }) == ("123456", "부산길")
    assert _provider_identity({"id": "123456"}) == ("123456", None)


@pytest.mark.parametrize(
    "profile",
    [
        [],
        {"id": True},
        {"id": -1},
        {"id": "not-numeric"},
        {"id": 123, "properties": []},
        {"id": 123, "properties": {"nickname": ""}},
        {"id": 123, "properties": {"nickname": "가" * 101}},
    ],
)
def test_kakao_provider_identity_rejects_invalid_contract(profile):
    with pytest.raises(ValueError):
        _provider_identity(profile)


def test_production_cookie_stays_secure_even_with_bad_redirect_config(
    monkeypatch,
):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(
        settings,
        "kakao_oauth_redirect_uri",
        "http://route.example.kr/api/auth/kakao/callback",
    )
    assert _secure_cookie() is True
