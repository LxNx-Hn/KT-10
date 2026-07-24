"""운영 설정의 보안·출처 판정 계약."""

from app.settings import Settings


def test_production_origin_security_requires_one_https_public_origin():
    insecure = Settings(
        _env_file=None,
        app_env="production",
        allowed_origins="http://route.example.kr",
        frontend_url="http://route.example.kr",
        kakao_oauth_redirect_uri=(
            "http://route.example.kr/api/auth/kakao/callback"
        ),
    )
    assert insecure.origin_security_configured is False

    secure = Settings(
        _env_file=None,
        app_env="production",
        allowed_origins="https://route.example.kr",
        frontend_url="https://route.example.kr/",
        kakao_oauth_redirect_uri=(
            "https://route.example.kr/api/auth/kakao/callback"
        ),
    )
    assert secure.origin_security_configured is True


def test_origin_security_rejects_wildcard_credentials_and_wrong_callback():
    wildcard = Settings(
        _env_file=None,
        allowed_origins="*",
        frontend_url="http://localhost:5173",
        kakao_oauth_redirect_uri=(
            "http://localhost:8002/api/auth/kakao/callback"
        ),
    )
    assert wildcard.origin_security_configured is False

    wrong_callback = Settings(
        _env_file=None,
        allowed_origins="http://localhost:5173",
        frontend_url="http://localhost:5173",
        kakao_oauth_redirect_uri="http://localhost:8002/callback",
    )
    assert wrong_callback.origin_security_configured is False


def test_readiness_requires_strong_session_secret_and_exact_database_driver():
    weak = Settings(
        _env_file=None,
        session_secret="short",
        database_url="postgresql://user:password@db/app",
    )
    assert weak.session_signing_configured is False
    assert weak.database_configured is False
    assert weak.deployment_readiness()["session_signing"] is False

    configured = Settings(
        _env_file=None,
        session_secret="s" * 32,
        database_url="postgresql+psycopg://user:password@db/app",
    )
    assert configured.session_signing_configured is True
    assert configured.database_configured is True


def test_whitespace_provider_keys_are_not_live():
    configured = Settings(
        _env_file=None,
        kakao_rest_api_key=" ",
        openweather_api_key="\t",
        bus_service_key="  ",
        vworld_api_key="\n",
        building_source="vworld",
    )
    assert configured.live_places is False
    assert configured.live_weather is False
    assert configured.live_bus is False
    assert configured.live_buildings is False


def test_whitespace_secrets_do_not_satisfy_readiness_or_login():
    configured = Settings(
        _env_file=None,
        allowed_origins="http://localhost:5173",
        frontend_url="http://localhost:5173",
        kakao_oauth_redirect_uri=(
            "http://localhost:8002/api/auth/kakao/callback"
        ),
        session_secret=" " * 32,
        labeling_api_token="\t" * 32,
        kakao_rest_api_key="kakao-rest",
        kakao_oauth_client_secret="\n",
        database_url=" postgresql+psycopg://user:password@db/app ",
    )

    assert configured.database_configured is True
    assert configured.session_signing_configured is False
    assert configured.kakao_login_configured is False
    assert configured.deployment_readiness()["labeling_batch_auth"] is False
