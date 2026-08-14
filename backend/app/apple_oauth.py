"""Apple Sign in with Apple OAuth/OIDC server-side verification.

This module isolates Apple protocol helpers. Public login/callback routes are
not wired here; callers must supply configuration and an HTTP client.
"""
from __future__ import annotations

import logging
import math
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm

from .settings import settings

log = logging.getLogger("apple_oauth")

APPLE_AUTHORIZATION_ENDPOINT = "https://appleid.apple.com/auth/authorize"
APPLE_TOKEN_ENDPOINT = "https://appleid.apple.com/auth/token"
APPLE_JWKS_ENDPOINT = "https://appleid.apple.com/auth/keys"
APPLE_ISSUER = "https://appleid.apple.com"
APPLE_ID_TOKEN_ALGORITHMS = ("RS256",)
APPLE_CLIENT_SECRET_TTL_SECONDS = 300
APPLE_CLOCK_SKEW_LEEWAY_SECONDS = 60
APPLE_AUTHORIZATION_CODE_MAX_LEN = 2048
APPLE_NONCE_MAX_LEN = 255
APPLE_PROVIDER_SUBJECT_MAX_LEN = 255
_STATE_NONCE_BYTES = 32
_MAX_EXPIRES_IN_SECONDS = 7 * 24 * 3600


class AppleOAuthError(Exception):
    """Safe Apple OAuth failure. Messages must not include tokens or keys."""


class AppleConfigurationError(AppleOAuthError):
    """Apple web OAuth is unavailable or the local signing key cannot be used."""


class AppleProviderError(AppleOAuthError):
    """Apple HTTP or token-response contract failed."""


class AppleTokenVerificationError(AppleOAuthError):
    """id_token signature or claim verification failed."""


@dataclass(frozen=True)
class AppleAuthorizationRequest:
    authorization_url: str
    state: str
    nonce: str


@dataclass(frozen=True)
class AppleTokenResponse:
    id_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    access_token: str | None = field(default=None, repr=False)
    token_type: str | None = None
    expires_in: int | None = None

    def __repr__(self) -> str:
        return (
            "AppleTokenResponse("
            f"token_type={self.token_type!r}, "
            f"expires_in={self.expires_in!r})"
        )


@dataclass(frozen=True)
class AppleVerifiedIdentity:
    provider_subject: str


@dataclass(frozen=True)
class AppleVerifiedAuthorization:
    provider_subject: str
    refresh_token: str = field(repr=False)
    access_token: str | None = field(default=None, repr=False)
    expires_in: int | None = None

    def __repr__(self) -> str:
        return (
            "AppleVerifiedAuthorization("
            f"provider_subject={self.provider_subject!r}, "
            f"expires_in={self.expires_in!r})"
        )


def _contains_control_characters(value: str) -> bool:
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


def _require_apple_web_oauth_configured() -> None:
    if not settings.apple_web_oauth_configured:
        raise AppleConfigurationError("Apple web OAuth is not configured.")


def _require_non_empty_str(value: object) -> str:
    if type(value) is not str or not value:
        raise AppleProviderError("Apple token response is invalid.")
    return value


def _require_authorization_code(code: object) -> str:
    if type(code) is not str or not code:
        raise AppleOAuthError("Apple authorization code is invalid.")
    if len(code) > APPLE_AUTHORIZATION_CODE_MAX_LEN:
        raise AppleOAuthError("Apple authorization code is invalid.")
    if _contains_control_characters(code):
        raise AppleOAuthError("Apple authorization code is invalid.")
    return code


def _validated_provider_subject(value: object) -> str:
    if type(value) is not str or not value:
        raise AppleTokenVerificationError("Apple id_token subject is invalid.")
    if len(value) > APPLE_PROVIDER_SUBJECT_MAX_LEN:
        raise AppleTokenVerificationError("Apple id_token subject is invalid.")
    if _contains_control_characters(value):
        raise AppleTokenVerificationError("Apple id_token subject is invalid.")
    return value


def _validated_nonce_value(value: object) -> str:
    if type(value) is not str or not value:
        raise AppleTokenVerificationError("Apple id_token nonce is invalid.")
    if len(value) > APPLE_NONCE_MAX_LEN:
        raise AppleTokenVerificationError("Apple id_token nonce is invalid.")
    if _contains_control_characters(value):
        raise AppleTokenVerificationError("Apple id_token nonce is invalid.")
    return value


def _new_state_and_nonce() -> tuple[str, str]:
    state = secrets.token_urlsafe(_STATE_NONCE_BYTES)
    nonce = secrets.token_urlsafe(_STATE_NONCE_BYTES)
    while not state or not nonce or nonce == state:
        nonce = secrets.token_urlsafe(_STATE_NONCE_BYTES)
    return state, nonce


def create_apple_authorization_request() -> AppleAuthorizationRequest:
    _require_apple_web_oauth_configured()
    state, nonce = _new_state_and_nonce()
    query = urlencode({
        "client_id": settings.apple_client_id,
        "redirect_uri": settings.apple_oauth_redirect_uri,
        "response_type": "code",
        "response_mode": "form_post",
        "state": state,
        "nonce": nonce,
    })
    return AppleAuthorizationRequest(
        authorization_url=f"{APPLE_AUTHORIZATION_ENDPOINT}?{query}",
        state=state,
        nonce=nonce,
    )


def generate_apple_client_secret(*, now: datetime | None = None) -> str:
    _require_apple_web_oauth_configured()
    issued_at = int((now or datetime.now(timezone.utc)).timestamp())
    try:
        return jwt.encode(
            {
                "iss": settings.apple_team_id,
                "iat": issued_at,
                "exp": issued_at + APPLE_CLIENT_SECRET_TTL_SECONDS,
                "aud": APPLE_ISSUER,
                "sub": settings.apple_client_id,
            },
            settings.apple_private_key.get_secret_value(),
            algorithm="ES256",
            headers={"kid": settings.apple_key_id, "alg": "ES256"},
        )
    except Exception:
        log.warning("Apple client_secret generation failed")
        raise AppleConfigurationError(
            "Apple client_secret could not be generated."
        ) from None


def _validated_token_response(payload: dict[str, Any]) -> AppleTokenResponse:
    id_token = _require_non_empty_str(payload.get("id_token"))
    refresh_token = _require_non_empty_str(payload.get("refresh_token"))
    access_token_raw = payload.get("access_token")
    if access_token_raw is None:
        access_token = None
    else:
        access_token = _require_non_empty_str(access_token_raw)

    token_type_raw = payload.get("token_type")
    if token_type_raw is None:
        token_type = None
    elif (
        type(token_type_raw) is not str
        or token_type_raw.casefold() != "bearer"
    ):
        raise AppleProviderError("Apple token response is invalid.")
    else:
        token_type = token_type_raw

    expires_in_raw = payload.get("expires_in")
    if expires_in_raw is None:
        expires_in = None
    elif (
        type(expires_in_raw) is not int
        or expires_in_raw <= 0
        or expires_in_raw > _MAX_EXPIRES_IN_SECONDS
    ):
        raise AppleProviderError("Apple token response is invalid.")
    else:
        expires_in = expires_in_raw

    return AppleTokenResponse(
        id_token=id_token,
        refresh_token=refresh_token,
        access_token=access_token,
        token_type=token_type,
        expires_in=expires_in,
    )


async def exchange_apple_authorization_code(
    code: str,
    *,
    client: httpx.AsyncClient,
) -> AppleTokenResponse:
    _require_apple_web_oauth_configured()
    validated_code = _require_authorization_code(code)
    client_secret = generate_apple_client_secret()
    try:
        response = await client.post(
            APPLE_TOKEN_ENDPOINT,
            data={
                "client_id": settings.apple_client_id,
                "client_secret": client_secret,
                "code": validated_code,
                "grant_type": "authorization_code",
                "redirect_uri": settings.apple_oauth_redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=settings.request_timeout,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError:
        log.warning("Apple token exchange failed (HTTPStatusError)")
        raise AppleProviderError("Apple token exchange failed.") from None
    except httpx.HTTPError:
        log.warning("Apple token exchange failed (HTTPError)")
        raise AppleProviderError("Apple token exchange failed.") from None

    try:
        payload = response.json()
    except ValueError:
        raise AppleProviderError("Apple token response is invalid.") from None
    if type(payload) is not dict:
        raise AppleProviderError("Apple token response is invalid.")
    return _validated_token_response(payload)


def _validated_jwks_keys(payload: object) -> list[dict[str, Any]]:
    if type(payload) is not dict:
        raise AppleTokenVerificationError("Apple JWKS response is invalid.")
    keys = payload.get("keys")
    if type(keys) is not list or not keys:
        raise AppleTokenVerificationError("Apple JWKS response is invalid.")
    validated: list[dict[str, Any]] = []
    for key in keys:
        if type(key) is not dict:
            raise AppleTokenVerificationError("Apple JWK is invalid.")
        kid = key.get("kid")
        if type(kid) is not str or not kid:
            raise AppleTokenVerificationError("Apple JWK is invalid.")
        validated.append(key)
    return validated


async def fetch_apple_jwks(*, client: httpx.AsyncClient) -> list[dict[str, Any]]:
    try:
        response = await client.get(
            APPLE_JWKS_ENDPOINT,
            timeout=settings.request_timeout,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError:
        log.warning("Apple JWKS fetch failed (HTTPStatusError)")
        raise AppleProviderError("Apple JWKS fetch failed.") from None
    except httpx.HTTPError:
        log.warning("Apple JWKS fetch failed (HTTPError)")
        raise AppleProviderError("Apple JWKS fetch failed.") from None
    try:
        payload = response.json()
    except ValueError:
        raise AppleTokenVerificationError("Apple JWKS response is invalid.") from None
    return _validated_jwks_keys(payload)


def _select_rsa_signing_jwk(
    keys: list[dict[str, Any]],
    kid: str,
) -> dict[str, Any]:
    matches = [key for key in keys if key.get("kid") == kid]
    if len(matches) != 1:
        raise AppleTokenVerificationError(
            "Apple id_token signing key is unavailable."
        )
    jwk = matches[0]
    if jwk.get("kty") != "RSA":
        raise AppleTokenVerificationError("Apple id_token signing key is invalid.")
    if "alg" in jwk and jwk.get("alg") != "RS256":
        raise AppleTokenVerificationError("Apple id_token signing key is invalid.")
    if "use" in jwk and jwk.get("use") != "sig":
        raise AppleTokenVerificationError("Apple id_token signing key is invalid.")
    if type(jwk.get("n")) is not str or not jwk["n"]:
        raise AppleTokenVerificationError("Apple id_token signing key is invalid.")
    if type(jwk.get("e")) is not str or not jwk["e"]:
        raise AppleTokenVerificationError("Apple id_token signing key is invalid.")
    return jwk


def _require_numeric_timestamp(value: object) -> int | float:
    if type(value) is not int and type(value) is not float:
        raise AppleTokenVerificationError("Apple id_token timestamp is invalid.")
    if not math.isfinite(value):
        raise AppleTokenVerificationError("Apple id_token timestamp is invalid.")
    return value


def verify_apple_id_token(
    id_token: str,
    expected_nonce: str,
    jwks: list[dict[str, Any]],
) -> AppleVerifiedIdentity:
    _require_apple_web_oauth_configured()
    expected_nonce = _validated_nonce_value(expected_nonce)
    if type(id_token) is not str or not id_token:
        raise AppleTokenVerificationError("Apple id_token is invalid.")

    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.InvalidTokenError:
        raise AppleTokenVerificationError(
            "Apple id_token header is invalid."
        ) from None
    if type(header) is not dict:
        raise AppleTokenVerificationError("Apple id_token header is invalid.")
    kid = header.get("kid")
    alg = header.get("alg")
    if type(kid) is not str or not kid:
        raise AppleTokenVerificationError("Apple id_token header is invalid.")
    if alg != "RS256":
        raise AppleTokenVerificationError(
            "Apple id_token algorithm is not allowed."
        )

    jwk = _select_rsa_signing_jwk(jwks, kid)
    try:
        public_key = RSAAlgorithm.from_jwk(jwk)
    except (jwt.PyJWTError, ValueError, TypeError):
        raise AppleTokenVerificationError(
            "Apple id_token signing key is invalid."
        ) from None
    try:
        claims = jwt.decode(
            id_token,
            key=public_key,
            algorithms=list(APPLE_ID_TOKEN_ALGORITHMS),
            audience=settings.apple_client_id,
            issuer=APPLE_ISSUER,
            leeway=APPLE_CLOCK_SKEW_LEEWAY_SECONDS,
            options={
                "require": ["iss", "aud", "exp", "iat", "sub", "nonce"],
                "verify_aud": True,
                "verify_iss": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_signature": True,
            },
        )
    except (jwt.PyJWTError, OverflowError, ValueError, TypeError):
        raise AppleTokenVerificationError(
            "Apple id_token verification failed."
        ) from None
    if type(claims) is not dict:
        raise AppleTokenVerificationError("Apple id_token claims are invalid.")

    if claims.get("iss") != APPLE_ISSUER:
        raise AppleTokenVerificationError("Apple id_token issuer is invalid.")
    if claims.get("aud") != settings.apple_client_id:
        raise AppleTokenVerificationError("Apple id_token audience is invalid.")

    now = time.time()
    iat = _require_numeric_timestamp(claims.get("iat"))
    exp = _require_numeric_timestamp(claims.get("exp"))
    if iat > now + APPLE_CLOCK_SKEW_LEEWAY_SECONDS:
        raise AppleTokenVerificationError("Apple id_token issued-at is invalid.")
    if exp <= now - APPLE_CLOCK_SKEW_LEEWAY_SECONDS:
        raise AppleTokenVerificationError("Apple id_token is expired.")

    provider_subject = _validated_provider_subject(claims.get("sub"))
    nonce = _validated_nonce_value(claims.get("nonce"))
    if not secrets.compare_digest(nonce, expected_nonce):
        raise AppleTokenVerificationError("Apple id_token nonce is invalid.")

    return AppleVerifiedIdentity(provider_subject=provider_subject)


async def verify_apple_authorization_code(
    code: str,
    expected_nonce: str,
    *,
    client: httpx.AsyncClient,
) -> AppleVerifiedAuthorization:
    _require_apple_web_oauth_configured()
    expected_nonce = _validated_nonce_value(expected_nonce)
    tokens = await exchange_apple_authorization_code(code, client=client)
    jwks = await fetch_apple_jwks(client=client)
    identity = verify_apple_id_token(tokens.id_token, expected_nonce, jwks)
    return AppleVerifiedAuthorization(
        provider_subject=identity.provider_subject,
        refresh_token=tokens.refresh_token,
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
    )
