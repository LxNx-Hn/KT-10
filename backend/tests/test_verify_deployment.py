"""운영 스모크가 Kakao 실제 공급자와 지정 장소명을 강제한다."""
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
