"""배포된 단일 출처 PWA와 실제 외부 공급자 연결을 끝까지 검증한다."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


def request(base: str, path: str, body: dict | None = None) -> tuple[dict | str, dict[str, str]]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = Request(f"{base}{path}", data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
            response_headers = {key.lower(): value for key, value in response.headers.items()}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"{path}: HTTP {exc.code} {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"{path}: 연결 실패 ({exc.reason})") from exc
    content_type = response_headers.get("content-type", "")
    if "json" in content_type:
        return json.loads(raw), response_headers
    return raw, response_headers


def verify_places(base: str) -> None:
    for query in ("부산역", "북구청"):
        places, place_headers = request(
            base,
            f"/api/places/search?{urlencode({'q': query})}",
        )
        if not isinstance(places, list) or not places:
            raise RuntimeError(f"Kakao 장소 검색이 '{query}' 결과를 반환하지 않았습니다.")
        names = [
            str(place.get("name") or "")
            for place in places
            if isinstance(place, dict)
        ]
        if not any(query in name.replace(" ", "") for name in names):
            raise RuntimeError(
                f"Kakao 장소 검색 결과에 요청한 '{query}' 장소명이 없습니다."
            )
        if place_headers.get("x-place-search-source") != "kakao-rest":
            raise RuntimeError("Kakao 장소 검색이 demo 공급자로 대체되었습니다.")


def verify(base: str) -> None:
    homepage, homepage_headers = request(base, "/")
    if not isinstance(homepage, str) or "부산 접근성 길찾기" not in homepage:
        raise RuntimeError("/: 운영 프론트 문서를 확인할 수 없습니다.")
    if f'{base}/og-route-preview.png' not in homepage:
        raise RuntimeError("/: 소셜 미리보기 URL이 배포 origin으로 치환되지 않았습니다.")
    if homepage_headers.get("x-content-type-options") != "nosniff":
        raise RuntimeError("/: Nginx 보안 헤더가 적용되지 않았습니다.")

    manifest, _ = request(base, "/manifest.webmanifest")
    if not isinstance(manifest, dict) or manifest.get("display") != "standalone":
        raise RuntimeError("/manifest.webmanifest: 설치형 PWA 계약이 올바르지 않습니다.")
    service_worker, _ = request(base, "/sw.js")
    if not isinstance(service_worker, str) or "workbox" not in service_worker:
        raise RuntimeError("/sw.js: 서비스 워커를 확인할 수 없습니다.")

    readiness, _ = request(base, "/api/readiness")
    if not isinstance(readiness, dict) or readiness.get("ready") is not True:
        missing = readiness.get("missing", []) if isinstance(readiness, dict) else []
        raise RuntimeError(f"/api/readiness: 운영 설정 미완료 ({', '.join(missing)})")

    verify_places(base)

    weather, _ = request(base, "/api/weather")
    if not isinstance(weather, dict) or "observedAt" not in weather:
        raise RuntimeError("실시간 날씨 응답 계약이 올바르지 않습니다.")

    stops, _ = request(base, f"/api/bus/stops?{urlencode({'q': '서면'})}")
    if not isinstance(stops, list):
        raise RuntimeError("부산 버스 정류장 응답 계약이 올바르지 않습니다.")

    departure = datetime.now(ZoneInfo("Asia/Seoul")).replace(
        hour=13, minute=0, second=0, microsecond=0
    ).isoformat()
    routes, _ = request(
        base,
        "/api/routes/recommend",
        {
            "origin": {
                "id": "deploy-busan-station",
                "name": "부산역",
                "lat": 35.1151,
                "lng": 129.0414,
            },
            "destination": {
                "id": "deploy-seomyeon-station",
                "name": "서면역",
                "lat": 35.1578,
                "lng": 129.0590,
            },
            "profile": "general",
            "weatherScenario": "normal",
            "options": {"departureAt": departure},
            "topN": 3,
        },
    )
    if not isinstance(routes, list) or not routes:
        raise RuntimeError("실경로 추천이 비어 있습니다.")
    for item in routes:
        route = item.get("route", {})
        if len(route.get("path", [])) < 2:
            raise RuntimeError("실경로 geometry가 없습니다.")
        if route.get("terrain", {}).get("status") == "unavailable":
            raise RuntimeError("경사도 계산 결과가 unavailable입니다.")
        if route.get("shade", {}).get("status") != "estimated_public":
            raise RuntimeError("VWorld 건물 기반 주간 그늘 계산이 완료되지 않았습니다.")

    print("배포 스모크 검증 완료: PWA, 보안 헤더, 장소, 날씨, 버스, 실경로, 경사도, 그늘")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8080", help="배포된 서비스 origin")
    args = parser.parse_args()
    try:
        verify(args.base.rstrip("/"))
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(f"배포 스모크 검증 실패: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
