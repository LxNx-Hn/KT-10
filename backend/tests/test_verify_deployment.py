"""운영 스모크가 Kakao 실제 공급자와 지정 장소명을 강제한다."""
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from scripts import verify_deployment


def test_verify_places_checks_both_queries_and_kakao_rest_source(monkeypatch):
    seen: list[str] = []

    def fake_request(base: str, path: str, body=None):
        query = parse_qs(urlparse(path).query)["q"][0]
        seen.append(query)
        return (
            [{"name": f"부산광역시 {query}"}],
            {"x-place-search-source": "kakao-rest"},
        )

    monkeypatch.setattr(verify_deployment, "request", fake_request)

    verify_deployment.verify_places("https://route.example.kr")

    assert seen == ["부산역", "북구청"]


def test_verify_places_rejects_demo_provider(monkeypatch):
    monkeypatch.setattr(
        verify_deployment,
        "request",
        lambda base, path, body=None: (
            [{"name": "부산역"}],
            {"x-place-search-source": "demo"},
        ),
    )

    with pytest.raises(RuntimeError, match="demo 공급자로 대체"):
        verify_deployment.verify_places("https://route.example.kr")


def test_verify_places_rejects_unrelated_results(monkeypatch):
    monkeypatch.setattr(
        verify_deployment,
        "request",
        lambda base, path, body=None: (
            [{"name": "전혀 다른 장소"}],
            {"x-place-search-source": "kakao-rest"},
        ),
    )

    with pytest.raises(RuntimeError, match="요청한 '부산역' 장소명"):
        verify_deployment.verify_places("https://route.example.kr")


def test_verify_weather_requires_fresh_provider_timestamps():
    now = datetime.now(UTC)
    verify_deployment.verify_weather({
        "observedAt": now.isoformat(),
        "airQualityObservedAt": (now - timedelta(minutes=5)).isoformat(),
    })

    with pytest.raises(RuntimeError, match="3시간보다 오래"):
        verify_deployment.verify_weather({
            "observedAt": (now - timedelta(hours=4)).isoformat(),
            "airQualityObservedAt": now.isoformat(),
        })


def test_verify_weather_rejects_missing_air_quality_timestamp():
    with pytest.raises(RuntimeError, match="대기질 관측시각이 없습니다"):
        verify_deployment.verify_weather({
            "observedAt": datetime.now(UTC).isoformat(),
        })


def test_verify_homepage_security_requires_hsts_without_server_version():
    verify_deployment.verify_homepage_security({
        "x-content-type-options": "nosniff",
        "strict-transport-security": "max-age=31536000; includeSubDomains",
        "server": "nginx",
    })

    with pytest.raises(RuntimeError, match="HSTS"):
        verify_deployment.verify_homepage_security({
            "x-content-type-options": "nosniff",
            "server": "nginx",
        })
    with pytest.raises(RuntimeError, match="버전을 노출"):
        verify_deployment.verify_homepage_security({
            "x-content-type-options": "nosniff",
            "strict-transport-security": "max-age=31536000",
            "server": "nginx/1.27.5",
        })
    verify_deployment.verify_homepage_security(
        {
            "x-content-type-options": "nosniff",
            "server": "nginx",
        },
        require_hsts=False,
    )


def test_request_rejects_non_http_or_credentialed_base_urls():
    with pytest.raises(RuntimeError, match=r"HTTP\(S\)"):
        verify_deployment.request("file:///tmp/service", "/api/health")
    with pytest.raises(RuntimeError, match=r"HTTP\(S\)"):
        verify_deployment.request(
            "https://user:password@route.example.kr",
            "/api/health",
        )


def test_public_deployment_base_requires_https():
    with pytest.raises(RuntimeError, match="HTTPS"):
        verify_deployment._validated_base("http://route.example.kr")

    assert verify_deployment._validated_base(
        "http://127.0.0.1:8080",
    ) == ("http", "127.0.0.1", 8080)


def test_request_rejects_cross_origin_redirect(monkeypatch):
    class RedirectedResponse:
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def geturl(self):
            return "https://unexpected.example/api/health"

        def read(self):
            return b"{}"

    monkeypatch.setattr(
        verify_deployment,
        "urlopen",
        lambda *_args, **_kwargs: RedirectedResponse(),
    )

    with pytest.raises(RuntimeError, match="redirect"):
        verify_deployment.request(
            "https://route.example.kr",
            "/api/health",
        )
