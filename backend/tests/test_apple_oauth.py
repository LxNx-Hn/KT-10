"""Apple OAuth/OIDC verification helpers. No live Apple network calls."""
from __future__ import annotations

import asyncio
import base64
import inspect
import json
import logging
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import RSAAlgorithm
from pydantic import SecretStr

from app import apple_oauth
from app.apple_oauth import (
    APPLE_AUTHORIZATION_ENDPOINT,
    APPLE_CLIENT_SECRET_TTL_SECONDS,
    APPLE_ISSUER,
    APPLE_JWKS_ENDPOINT,
    APPLE_NONCE_MAX_LEN,
    APPLE_TOKEN_ENDPOINT,
    AppleConfigurationError,
    AppleOAuthError,
    AppleProviderError,
    AppleTokenResponse,
    AppleTokenVerificationError,
    AppleVerifiedAuthorization,
    AppleVerifiedIdentity,
    create_apple_authorization_request,
    exchange_apple_authorization_code,
    fetch_apple_jwks,
    generate_apple_client_secret,
    verify_apple_authorization_code,
    verify_apple_id_token,
)
from app.settings import Settings, settings

CLIENT_ID = "com.example.test.service"
TEAM_ID = "TESTTEAMID"
KEY_ID = "TESTKEYID1"
REDIRECT_URI = "https://app.example.com/api/auth/apple/callback"
SUBJECT = "001234.apple-stable-subject"
NONCE = "expected-nonce-value-from-auth-request"
KID = "test-rsa-kid"


def _run(coro):
    return asyncio.run(coro)


def _ec_p256_pem():
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return pem, key.public_key()


def _rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _rsa_jwk(public_key, kid, **extra):
    jwk = json.loads(RSAAlgorithm.to_jwk(public_key))
    jwk["kid"] = kid
    jwk.update(extra)
    return jwk


def _valid_apple_kwargs(**overrides):
    values = {
        "apple_client_id": CLIENT_ID,
        "apple_team_id": TEAM_ID,
        "apple_key_id": KEY_ID,
        "apple_private_key": "test-apple-p8-placeholder",
        "apple_oauth_redirect_uri": REDIRECT_URI,
    }
    values.update(overrides)
    return values


def _configure_apple(monkeypatch, *, pem: str, **overrides):
    values = _valid_apple_kwargs(apple_private_key=SecretStr(pem), **overrides)
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)
    return values


class _Missing:
    pass


_MISSING = _Missing()


def _valid_claims(**overrides):
    now = int(time.time())
    claims = {
        "iss": APPLE_ISSUER,
        "aud": CLIENT_ID,
        "exp": now + 600,
        "iat": now,
        "sub": SUBJECT,
        "nonce": NONCE,
        "email": "hidden@privaterelay.appleid.com",
    }
    for key, value in overrides.items():
        if value is _MISSING:
            claims.pop(key, None)
        else:
            claims[key] = value
    return claims


def _sign_id_token(private_key, claims, *, kid=KID, algorithm="RS256"):
    return jwt.encode(
        claims,
        private_key,
        algorithm=algorithm,
        headers={"kid": kid, "alg": algorithm},
    )


def _unsigned_token(claims, *, kid=KID):
    def b64url(data: dict) -> str:
        raw = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{b64url({'alg': 'none', 'kid': kid})}.{b64url(claims)}."


def _assert_not_leaked(haystack: str, *secrets: str) -> None:
    for value in secrets:
        if value:
            assert value not in haystack


def _auth_query(authorization_url: str) -> dict[str, list[str]]:
    parsed = urlparse(authorization_url)
    return parse_qs(parsed.query, keep_blank_values=True)


def _form_body(request: httpx.Request) -> dict[str, list[str]]:
    return parse_qs(request.content.decode(), keep_blank_values=True)


def test_config_complete_valid_is_configured():
    configured = Settings(_env_file=None, **_valid_apple_kwargs())
    assert configured.apple_web_oauth_configured is True


def test_config_missing_client_id_is_not_configured():
    configured = Settings(
        _env_file=None,
        **_valid_apple_kwargs(apple_client_id=""),
    )
    assert configured.apple_web_oauth_configured is False


def test_config_missing_team_id_is_not_configured():
    configured = Settings(
        _env_file=None,
        **_valid_apple_kwargs(apple_team_id=""),
    )
    assert configured.apple_web_oauth_configured is False


def test_config_missing_key_id_is_not_configured():
    configured = Settings(
        _env_file=None,
        **_valid_apple_kwargs(apple_key_id=""),
    )
    assert configured.apple_web_oauth_configured is False


def test_config_missing_private_key_is_not_configured():
    configured = Settings(
        _env_file=None,
        **_valid_apple_kwargs(apple_private_key=""),
    )
    assert configured.apple_web_oauth_configured is False


def test_config_http_redirect_is_not_configured():
    configured = Settings(
        _env_file=None,
        **_valid_apple_kwargs(
            apple_oauth_redirect_uri=(
                "http://app.example.com/api/auth/apple/callback"
            ),
        ),
    )
    assert configured.apple_web_oauth_configured is False


def test_config_localhost_redirect_is_not_configured():
    configured = Settings(
        _env_file=None,
        **_valid_apple_kwargs(
            apple_oauth_redirect_uri="https://localhost/api/auth/apple/callback",
        ),
    )
    assert configured.apple_web_oauth_configured is False


def test_config_loopback_ip_redirect_is_not_configured():
    configured = Settings(
        _env_file=None,
        **_valid_apple_kwargs(
            apple_oauth_redirect_uri="https://127.0.0.1/api/auth/apple/callback",
        ),
    )
    assert configured.apple_web_oauth_configured is False


def test_config_ip_literal_redirect_is_not_configured():
    configured = Settings(
        _env_file=None,
        **_valid_apple_kwargs(
            apple_oauth_redirect_uri="https://8.8.8.8/api/auth/apple/callback",
        ),
    )
    assert configured.apple_web_oauth_configured is False


def test_config_redirect_with_fragment_is_not_configured():
    configured = Settings(
        _env_file=None,
        **_valid_apple_kwargs(
            apple_oauth_redirect_uri=(
                "https://app.example.com/api/auth/apple/callback#frag"
            ),
        ),
    )
    assert configured.apple_web_oauth_configured is False


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "https://[::1]/api/auth/apple/callback",
        "https://[2001:db8::1]/api/auth/apple/callback",
        "https://user:pass@app.example.com/api/auth/apple/callback",
        "https://app.example.com:abc/api/auth/apple/callback",
        "https://app.example.com:65536/api/auth/apple/callback",
        "https:///api/auth/apple/callback",
        "//app.example.com/api/auth/apple/callback",
        "javascript:alert(1)",
        "data:text/html,hi",
        "file:///etc/passwd",
    ],
)
def test_config_redirect_additional_fail_closed_urls(redirect_uri):
    configured = Settings(
        _env_file=None,
        **_valid_apple_kwargs(apple_oauth_redirect_uri=redirect_uri),
    )
    assert configured.apple_web_oauth_configured is False


def test_config_does_not_casefold_client_id():
    mixed = "com.Example.Test.Service"
    configured = Settings(
        _env_file=None,
        **_valid_apple_kwargs(apple_client_id=mixed),
    )
    assert configured.apple_client_id == mixed
    assert configured.apple_web_oauth_configured is True


def test_unconfigured_helpers_fail_closed_without_mock(monkeypatch):
    monkeypatch.setattr(settings, "apple_client_id", "")
    monkeypatch.setattr(settings, "apple_team_id", "")
    monkeypatch.setattr(settings, "apple_key_id", "")
    monkeypatch.setattr(settings, "apple_private_key", SecretStr(""))
    monkeypatch.setattr(settings, "apple_oauth_redirect_uri", "")
    with pytest.raises(AppleConfigurationError):
        create_apple_authorization_request()
    with pytest.raises(AppleConfigurationError):
        generate_apple_client_secret()


def test_authorization_request_uses_apple_constants_and_form_post(monkeypatch):
    pem, _public = _ec_p256_pem()
    _configure_apple(monkeypatch, pem=pem)
    request = create_apple_authorization_request()
    parsed = urlparse(request.authorization_url)
    assert parsed._replace(query="", fragment="").geturl() == (
        APPLE_AUTHORIZATION_ENDPOINT
    )
    params = _auth_query(request.authorization_url)
    assert params["client_id"] == [CLIENT_ID]
    assert params["redirect_uri"] == [REDIRECT_URI]
    assert params["response_type"] == ["code"]
    assert params["response_mode"] == ["form_post"]
    assert params["state"] == [request.state]
    assert params["nonce"] == [request.nonce]
    assert request.state
    assert request.nonce
    assert request.state != request.nonce


def test_authorization_request_state_and_nonce_are_unique(monkeypatch):
    pem, _public = _ec_p256_pem()
    _configure_apple(monkeypatch, pem=pem)
    first = create_apple_authorization_request()
    second = create_apple_authorization_request()
    assert first.state != second.state
    assert first.nonce != second.nonce
    assert first.state != first.nonce
    assert second.state != second.nonce


def test_authorization_request_omits_secrets_email_and_name(monkeypatch):
    pem, _public = _ec_p256_pem()
    _configure_apple(monkeypatch, pem=pem)
    request = create_apple_authorization_request()
    params = _auth_query(request.authorization_url)
    assert "scope" not in params
    assert "email" not in params
    assert "name" not in params
    assert "client_secret" not in params
    assert pem not in request.authorization_url
    assert "BEGIN" not in request.authorization_url


def test_authorization_helpers_do_not_accept_endpoint_overrides():
    for func in (
        create_apple_authorization_request,
        generate_apple_client_secret,
        exchange_apple_authorization_code,
        fetch_apple_jwks,
        verify_apple_id_token,
        verify_apple_authorization_code,
    ):
        names = set(inspect.signature(func).parameters)
        assert "url" not in names
        assert "authorization_url" not in names
        assert "token_url" not in names
        assert "jwks_url" not in names
        assert "issuer" not in names
        assert "audience" not in names
        assert "redirect_uri" not in names


def test_id_token_verification_requires_expected_nonce():
    parameter = inspect.signature(verify_apple_id_token).parameters["expected_nonce"]
    assert parameter.default is inspect.Parameter.empty


def test_client_secret_es256_claims_and_header(monkeypatch):
    pem, public_key = _ec_p256_pem()
    _configure_apple(monkeypatch, pem=pem)
    now = datetime.now(timezone.utc)
    secret = generate_apple_client_secret(now=now)
    header = jwt.get_unverified_header(secret)
    assert header["alg"] == "ES256"
    assert header["kid"] == KEY_ID
    claims = jwt.decode(
        secret,
        public_key,
        algorithms=["ES256"],
        audience=APPLE_ISSUER,
        options={"require": ["iss", "aud", "exp", "iat", "sub"]},
    )
    issued_at = int(now.timestamp())
    assert claims["iss"] == TEAM_ID
    assert claims["sub"] == CLIENT_ID
    assert claims["aud"] == APPLE_ISSUER
    assert claims["iat"] == issued_at
    assert claims["exp"] == issued_at + APPLE_CLIENT_SECRET_TTL_SECONDS
    assert claims["exp"] > claims["iat"]
    assert claims["exp"] - claims["iat"] <= APPLE_CLIENT_SECRET_TTL_SECONDS


def test_client_secret_wrong_private_key_is_invalid(monkeypatch):
    pem, _public = _ec_p256_pem()
    _other_pem, other_public = _ec_p256_pem()
    _configure_apple(monkeypatch, pem=pem)
    secret = generate_apple_client_secret()
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(
            secret,
            other_public,
            algorithms=["ES256"],
            audience=APPLE_ISSUER,
        )


def test_client_secret_and_private_key_stay_out_of_logs_and_exceptions(
    monkeypatch,
    caplog,
):
    pem, _public = _ec_p256_pem()
    _configure_apple(monkeypatch, pem=pem)
    with caplog.at_level(logging.DEBUG):
        secret = generate_apple_client_secret()
        _assert_not_leaked(caplog.text, pem, secret)
        _assert_not_leaked(repr(settings), pem, secret)
        monkeypatch.setattr(settings, "apple_private_key", SecretStr("not-a-real-p8"))
        with pytest.raises(AppleConfigurationError) as exc:
            generate_apple_client_secret()
    _assert_not_leaked(str(exc.value), pem, secret, "not-a-real-p8")
    _assert_not_leaked(repr(exc.value), pem, secret, "not-a-real-p8")


def _token_payload(**overrides):
    payload = {
        "id_token": "header.payload.signature",
        "refresh_token": "apple-refresh-token",
        "access_token": "apple-access-token",
        "token_type": "Bearer",
        "expires_in": 3600,
    }
    payload.update(overrides)
    return payload


def _exchange_payload(monkeypatch, payload):
    pem, _public = _ec_p256_pem()
    _configure_apple(monkeypatch, pem=pem)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    async def _exercise():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            return await exchange_apple_authorization_code(
                "ok-code",
                client=client,
            )

    return _run(_exercise())


def test_token_exchange_posts_form_to_apple_token_endpoint(monkeypatch):
    pem, _public = _ec_p256_pem()
    _configure_apple(monkeypatch, pem=pem)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_token_payload(), request=request)

    async def _exercise():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            return await exchange_apple_authorization_code(
                "apple-auth-code",
                client=client,
            )

    result = _run(_exercise())
    assert isinstance(result, AppleTokenResponse)
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == APPLE_TOKEN_ENDPOINT
    assert request.method == "POST"
    assert request.headers["content-type"].startswith(
        "application/x-www-form-urlencoded"
    )
    body = _form_body(request)
    assert body["client_id"] == [CLIENT_ID]
    assert body["code"] == ["apple-auth-code"]
    assert body["grant_type"] == ["authorization_code"]
    assert body["redirect_uri"] == [REDIRECT_URI]
    assert body["client_secret"]
    assert result.refresh_token == "apple-refresh-token"
    assert "apple-refresh-token" not in repr(result)
    assert "apple-access-token" not in repr(result)
    assert "header.payload.signature" not in repr(result)


@pytest.mark.parametrize("token_type", ["Bearer", "bearer", "BEARER"])
def test_token_type_bearer_is_case_insensitive(monkeypatch, token_type):
    result = _exchange_payload(monkeypatch, _token_payload(token_type=token_type))
    assert result.token_type == token_type


@pytest.mark.parametrize(
    "token_type",
    [" bearer ", "Basic", True, 1, ["Bearer"]],
)
def test_token_type_malformed_values_are_rejected(monkeypatch, token_type):
    with pytest.raises(AppleProviderError):
        _exchange_payload(monkeypatch, _token_payload(token_type=token_type))


@pytest.mark.parametrize("status_code", [400, 401, 500, 503])
def test_token_exchange_http_errors_are_safe(monkeypatch, status_code, caplog):
    pem, _public = _ec_p256_pem()
    _configure_apple(monkeypatch, pem=pem)
    code = "leaky-authorization-code"
    provider_body = (
        '{"error":"invalid_grant","error_description":"leaky-authorization-code"}'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=provider_body, request=request)

    async def _exercise():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            await exchange_apple_authorization_code(code, client=client)

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(AppleProviderError) as exc:
            _run(_exercise())
    assert isinstance(exc.value, AppleOAuthError)
    _assert_not_leaked(str(exc.value), code, provider_body, pem)
    _assert_not_leaked(caplog.text, code, provider_body, pem)


def test_token_exchange_malformed_json_fails_safely(monkeypatch):
    pem, _public = _ec_p256_pem()
    _configure_apple(monkeypatch, pem=pem)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json {", request=request)

    async def _exercise():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            await exchange_apple_authorization_code("ok-code", client=client)

    with pytest.raises(AppleProviderError) as exc:
        _run(_exercise())
    assert "not-json" not in str(exc.value)


def test_token_exchange_missing_id_token_fails(monkeypatch):
    pem, _public = _ec_p256_pem()
    _configure_apple(monkeypatch, pem=pem)

    def handler(request: httpx.Request) -> httpx.Response:
        payload = _token_payload()
        del payload["id_token"]
        return httpx.Response(200, json=payload, request=request)

    async def _exercise():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            await exchange_apple_authorization_code("ok-code", client=client)

    with pytest.raises(AppleProviderError):
        _run(_exercise())


def test_token_exchange_missing_refresh_token_fails(monkeypatch):
    pem, _public = _ec_p256_pem()
    _configure_apple(monkeypatch, pem=pem)

    def handler(request: httpx.Request) -> httpx.Response:
        payload = _token_payload()
        del payload["refresh_token"]
        return httpx.Response(200, json=payload, request=request)

    async def _exercise():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            await exchange_apple_authorization_code("ok-code", client=client)

    with pytest.raises(AppleProviderError):
        _run(_exercise())


def test_token_exchange_rejects_control_characters_in_code(monkeypatch):
    pem, _public = _ec_p256_pem()
    _configure_apple(monkeypatch, pem=pem)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("authorization code must be rejected locally")

    async def _exercise():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            await exchange_apple_authorization_code("abc\ncode", client=client)

    with pytest.raises(AppleOAuthError):
        _run(_exercise())


def test_jwks_selects_matching_kid_among_multiple_keys(monkeypatch):
    pem, _public = _ec_p256_pem()
    _configure_apple(monkeypatch, pem=pem)
    signer = _rsa_key()
    other = _rsa_key()
    matching = _rsa_jwk(signer.public_key(), KID, use="sig", alg="RS256")
    other_jwk = _rsa_jwk(other.public_key(), "other-kid", use="sig", alg="RS256")
    token = _sign_id_token(signer, _valid_claims())
    identity = verify_apple_id_token(token, NONCE, [other_jwk, matching])
    assert identity == AppleVerifiedIdentity(provider_subject=SUBJECT)


def test_jwks_unknown_kid_fails(monkeypatch):
    pem, _public = _ec_p256_pem()
    _configure_apple(monkeypatch, pem=pem)
    signer = _rsa_key()
    other = _rsa_key()
    token = _sign_id_token(signer, _valid_claims(), kid="missing-kid")
    with pytest.raises(AppleTokenVerificationError):
        verify_apple_id_token(
            token,
            NONCE,
            [_rsa_jwk(other.public_key(), "present-kid", use="sig", alg="RS256")],
        )


def test_jwks_duplicate_kid_fails_closed(monkeypatch):
    pem, _public = _ec_p256_pem()
    _configure_apple(monkeypatch, pem=pem)
    signer = _rsa_key()
    other = _rsa_key()
    token = _sign_id_token(signer, _valid_claims())
    keys = [
        _rsa_jwk(signer.public_key(), KID, use="sig", alg="RS256"),
        _rsa_jwk(other.public_key(), KID, use="sig", alg="RS256"),
    ]
    with pytest.raises(AppleTokenVerificationError):
        verify_apple_id_token(token, NONCE, keys)


def test_jwks_malformed_keys_payload_fails(monkeypatch):
    pem, _public = _ec_p256_pem()
    _configure_apple(monkeypatch, pem=pem)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"keys": "not-a-list"}, request=request)

    async def _exercise():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            await fetch_apple_jwks(client=client)

    with pytest.raises(AppleTokenVerificationError):
        _run(_exercise())


def test_jwks_wrong_kty_fails(monkeypatch):
    pem, _public = _ec_p256_pem()
    _configure_apple(monkeypatch, pem=pem)
    signer = _rsa_key()
    token = _sign_id_token(signer, _valid_claims())
    jwk = _rsa_jwk(signer.public_key(), KID, use="sig", alg="RS256")
    jwk["kty"] = "EC"
    with pytest.raises(AppleTokenVerificationError):
        verify_apple_id_token(token, NONCE, [jwk])


def test_jwks_incompatible_alg_fails(monkeypatch):
    pem, _public = _ec_p256_pem()
    _configure_apple(monkeypatch, pem=pem)
    signer = _rsa_key()
    token = _sign_id_token(signer, _valid_claims())
    jwk = _rsa_jwk(signer.public_key(), KID, use="sig", alg="ES256")
    with pytest.raises(AppleTokenVerificationError):
        verify_apple_id_token(token, NONCE, [jwk])


def test_fetch_apple_jwks_uses_constant_endpoint(monkeypatch):
    pem, _public = _ec_p256_pem()
    _configure_apple(monkeypatch, pem=pem)
    requests: list[httpx.Request] = []
    signer = _rsa_key()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "keys": [
                    _rsa_jwk(signer.public_key(), KID, use="sig", alg="RS256"),
                ],
            },
            request=request,
        )

    async def _exercise():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            return await fetch_apple_jwks(client=client)

    keys = _run(_exercise())
    assert str(requests[0].url) == APPLE_JWKS_ENDPOINT
    assert requests[0].method == "GET"
    assert keys[0]["kid"] == KID


def _verify(monkeypatch, token, nonce=NONCE, jwks=None, private_key=None):
    pem, _public = _ec_p256_pem()
    _configure_apple(monkeypatch, pem=pem)
    signer = private_key or _rsa_key()
    keys = jwks or [_rsa_jwk(signer.public_key(), KID, use="sig", alg="RS256")]
    return verify_apple_id_token(token, nonce, keys), signer, keys


def test_valid_id_token_returns_provider_subject(monkeypatch):
    signer = _rsa_key()
    token = _sign_id_token(signer, _valid_claims())
    identity, _signer, _keys = _verify(monkeypatch, token, private_key=signer)
    assert identity.provider_subject == SUBJECT
    assert "email" not in identity.__dataclass_fields__


def test_forged_signature_fails(monkeypatch):
    signer = _rsa_key()
    forger = _rsa_key()
    token = _sign_id_token(forger, _valid_claims())
    pem, _public = _ec_p256_pem()
    _configure_apple(monkeypatch, pem=pem)
    with pytest.raises(AppleTokenVerificationError):
        verify_apple_id_token(
            token,
            NONCE,
            [_rsa_jwk(signer.public_key(), KID, use="sig", alg="RS256")],
        )


def test_wrong_issuer_fails(monkeypatch):
    signer = _rsa_key()
    token = _sign_id_token(
        signer,
        _valid_claims(iss="https://evil.example"),
    )
    with pytest.raises(AppleTokenVerificationError):
        _verify(monkeypatch, token, private_key=signer)


def test_wrong_audience_fails(monkeypatch):
    signer = _rsa_key()
    token = _sign_id_token(
        signer,
        _valid_claims(aud="com.example.other.service"),
    )
    with pytest.raises(AppleTokenVerificationError):
        _verify(monkeypatch, token, private_key=signer)


def test_expired_token_fails(monkeypatch):
    signer = _rsa_key()
    now = int(time.time())
    token = _sign_id_token(
        signer,
        _valid_claims(iat=now - 400, exp=now - 120),
    )
    with pytest.raises(AppleTokenVerificationError):
        _verify(monkeypatch, token, private_key=signer)


def test_iat_too_far_future_fails(monkeypatch):
    signer = _rsa_key()
    now = int(time.time())
    token = _sign_id_token(
        signer,
        _valid_claims(iat=now + 120, exp=now + 720),
    )
    with pytest.raises(AppleTokenVerificationError):
        _verify(monkeypatch, token, private_key=signer)


@pytest.mark.parametrize(
    "claim,value",
    [
        ("iat", True),
        ("iat", False),
        ("exp", True),
        ("exp", False),
        ("iat", float("nan")),
        ("exp", float("nan")),
        ("iat", float("inf")),
        ("exp", float("inf")),
        ("exp", float("-inf")),
    ],
)
def test_iat_exp_non_finite_or_bool_timestamps_fail(monkeypatch, claim, value):
    signer = _rsa_key()
    token = _sign_id_token(signer, _valid_claims(**{claim: value}))
    with pytest.raises(AppleTokenVerificationError):
        _verify(monkeypatch, token, private_key=signer)


def test_missing_exp_fails(monkeypatch):
    signer = _rsa_key()
    token = _sign_id_token(signer, _valid_claims(exp=_MISSING))
    with pytest.raises(AppleTokenVerificationError):
        _verify(monkeypatch, token, private_key=signer)


def test_missing_iat_fails(monkeypatch):
    signer = _rsa_key()
    token = _sign_id_token(signer, _valid_claims(iat=_MISSING))
    with pytest.raises(AppleTokenVerificationError):
        _verify(monkeypatch, token, private_key=signer)


def test_missing_sub_fails(monkeypatch):
    signer = _rsa_key()
    token = _sign_id_token(signer, _valid_claims(sub=_MISSING))
    with pytest.raises(AppleTokenVerificationError):
        _verify(monkeypatch, token, private_key=signer)


def test_empty_sub_fails(monkeypatch):
    signer = _rsa_key()
    token = _sign_id_token(signer, _valid_claims(sub=""))
    with pytest.raises(AppleTokenVerificationError):
        _verify(monkeypatch, token, private_key=signer)


def test_sub_longer_than_255_fails(monkeypatch):
    signer = _rsa_key()
    token = _sign_id_token(signer, _valid_claims(sub="a" * 256))
    with pytest.raises(AppleTokenVerificationError):
        _verify(monkeypatch, token, private_key=signer)


def test_sub_control_character_fails(monkeypatch):
    signer = _rsa_key()
    token = _sign_id_token(signer, _valid_claims(sub="abc\n123"))
    with pytest.raises(AppleTokenVerificationError):
        _verify(monkeypatch, token, private_key=signer)


def test_missing_nonce_fails(monkeypatch):
    signer = _rsa_key()
    token = _sign_id_token(signer, _valid_claims(nonce=_MISSING))
    with pytest.raises(AppleTokenVerificationError):
        _verify(monkeypatch, token, private_key=signer)


def test_wrong_nonce_fails(monkeypatch):
    signer = _rsa_key()
    token = _sign_id_token(signer, _valid_claims(nonce="different-nonce"))
    with pytest.raises(AppleTokenVerificationError):
        _verify(monkeypatch, token, private_key=signer)


def test_empty_nonce_fails(monkeypatch):
    signer = _rsa_key()
    token = _sign_id_token(signer, _valid_claims(nonce=""))
    with pytest.raises(AppleTokenVerificationError):
        _verify(monkeypatch, token, private_key=signer)


def test_expected_nonce_none_cannot_bypass_verification(monkeypatch):
    signer = _rsa_key()
    token = _sign_id_token(signer, _valid_claims())
    with pytest.raises(AppleTokenVerificationError):
        _verify(monkeypatch, token, nonce=None, private_key=signer)


def test_expected_nonce_too_long_fails(monkeypatch):
    signer = _rsa_key()
    token = _sign_id_token(signer, _valid_claims())
    with pytest.raises(AppleTokenVerificationError):
        _verify(
            monkeypatch,
            token,
            nonce="n" * (APPLE_NONCE_MAX_LEN + 1),
            private_key=signer,
        )


def test_wrong_kid_fails(monkeypatch):
    signer = _rsa_key()
    token = _sign_id_token(signer, _valid_claims(), kid="other-kid")
    with pytest.raises(AppleTokenVerificationError):
        _verify(monkeypatch, token, private_key=signer)


def test_algorithm_confusion_hs256_fails(monkeypatch):
    signer = _rsa_key()
    token = jwt.encode(
        _valid_claims(),
        "hmac-secret-for-algorithm-confusion-tests",
        algorithm="HS256",
        headers={"kid": KID, "alg": "HS256"},
    )
    with pytest.raises(AppleTokenVerificationError):
        _verify(monkeypatch, token, private_key=signer)


def test_unsigned_alg_none_fails(monkeypatch):
    signer = _rsa_key()
    token = _unsigned_token(_valid_claims())
    with pytest.raises(AppleTokenVerificationError):
        _verify(monkeypatch, token, private_key=signer)


def test_identity_is_sub_even_when_email_differs(monkeypatch):
    signer = _rsa_key()
    first = _sign_id_token(
        signer,
        _valid_claims(email="one@example.com"),
    )
    second = _sign_id_token(
        signer,
        _valid_claims(email="two@example.com"),
    )
    first_identity, _signer, keys = _verify(
        monkeypatch,
        first,
        private_key=signer,
    )
    second_identity = verify_apple_id_token(second, NONCE, keys)
    assert first_identity.provider_subject == SUBJECT
    assert second_identity.provider_subject == SUBJECT


def test_same_email_different_sub_are_not_account_linked(monkeypatch):
    signer = _rsa_key()
    other_sub = "009999.other-apple-subject"
    first = _sign_id_token(
        signer,
        _valid_claims(sub=SUBJECT, email="same@example.com"),
    )
    second = _sign_id_token(
        signer,
        _valid_claims(sub=other_sub, email="same@example.com"),
    )
    first_identity, _signer, keys = _verify(
        monkeypatch,
        first,
        private_key=signer,
    )
    second_identity = verify_apple_id_token(second, NONCE, keys)
    assert first_identity.provider_subject == SUBJECT
    assert second_identity.provider_subject == other_sub
    assert first_identity.provider_subject != second_identity.provider_subject


def test_audience_list_is_rejected(monkeypatch):
    signer = _rsa_key()
    token = _sign_id_token(
        signer,
        _valid_claims(aud=[CLIENT_ID]),
    )
    with pytest.raises(AppleTokenVerificationError):
        _verify(monkeypatch, token, private_key=signer)


def test_verify_authorization_code_returns_subject_without_id_token(
    monkeypatch,
    caplog,
):
    pem, _public = _ec_p256_pem()
    _configure_apple(monkeypatch, pem=pem)
    signer = _rsa_key()
    id_token = _sign_id_token(signer, _valid_claims())
    refresh_token = f"refresh-{uuid4()}"
    access_token = f"access-{uuid4()}"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and str(request.url) == APPLE_TOKEN_ENDPOINT:
            return httpx.Response(
                200,
                json=_token_payload(
                    id_token=id_token,
                    refresh_token=refresh_token,
                    access_token=access_token,
                ),
                request=request,
            )
        if request.method == "GET" and str(request.url) == APPLE_JWKS_ENDPOINT:
            return httpx.Response(
                200,
                json={
                    "keys": [
                        _rsa_jwk(
                            signer.public_key(),
                            KID,
                            use="sig",
                            alg="RS256",
                        ),
                    ],
                },
                request=request,
            )
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    async def _exercise():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
        ) as client:
            return await verify_apple_authorization_code(
                "apple-auth-code",
                NONCE,
                client=client,
            )

    with caplog.at_level(logging.DEBUG):
        result = _run(_exercise())
    assert isinstance(result, AppleVerifiedAuthorization)
    assert result.provider_subject == SUBJECT
    assert result.refresh_token == refresh_token
    assert result.access_token == access_token
    assert not hasattr(result, "id_token")
    leaked = (id_token, refresh_token, access_token, pem, "apple-auth-code")
    _assert_not_leaked(repr(result), *leaked)
    _assert_not_leaked(caplog.text, *leaked)


def test_settings_repr_hides_apple_private_key():
    pem, _public = _ec_p256_pem()
    configured = Settings(_env_file=None, **_valid_apple_kwargs(apple_private_key=pem))
    rendered = repr(configured)
    assert configured.apple_web_oauth_configured is True
    assert pem not in rendered
    assert "BEGIN" not in rendered
    dumped = configured.model_dump(mode="json")
    assert pem not in str(dumped)
    assert dumped["apple_private_key"] != pem


def test_apple_oauth_module_does_not_register_public_routes():
    source = inspect.getsource(apple_oauth)
    assert "/api/auth/apple" not in source
    assert "APIRouter" not in source
    assert "include_router" not in source
