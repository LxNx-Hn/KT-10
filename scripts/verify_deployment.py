"""배포된 단일 출처 PWA와 실제 외부 공급자 연결을 끝까지 검증한다."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import math
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

LOCAL_ONLY_READINESS_GAPS = frozenset({"origin_security", "kakao_login"})


def _url_origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise RuntimeError(
            "HTTP(S) origin 형식의 배포 URL만 검증할 수 있습니다."
        )
    if (
        parsed.scheme == "http"
        and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
    ):
        raise RuntimeError("공개 배포 URL은 HTTPS여야 합니다.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError("배포 URL 포트가 올바르지 않습니다.") from exc
    return parsed.scheme, parsed.hostname, port


def _validated_base(base: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(base)
    if (
        parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(
            "HTTP(S) origin 형식의 배포 URL만 검증할 수 있습니다."
        )
    return _url_origin(base)


def request(base: str, path: str, body: dict | None = None) -> tuple[dict | str, dict[str, str]]:
    expected_origin = _validated_base(base)
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    url = f"{base}{path}"
    req = Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        # URL scheme/host/credentials를 위에서 제한한 배포 검증 전용 요청이다.
        with urlopen(req, timeout=30) as response:  # nosec B310
            if _url_origin(response.geturl()) != expected_origin:
                raise RuntimeError(
                    f"{path}: 다른 origin 또는 protocol로 redirect됐습니다."
                )
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


def verify_places(base: str) -> dict[str, dict]:
    selected_places: dict[str, dict] = {}
    for query in ("부산역", "북구청"):
        places, place_headers = request(
            base,
            f"/api/places/search?{urlencode({'q': query})}",
        )
        if not isinstance(places, list) or not places:
            raise RuntimeError(f"Kakao 장소 검색이 '{query}' 결과를 반환하지 않았습니다.")
        selected = next(
            (
                place
                for place in places
                if isinstance(place, dict)
                and query in str(place.get("name") or "").replace(" ", "")
            ),
            None,
        )
        if selected is None:
            raise RuntimeError(
                f"Kakao 장소 검색 결과에 요청한 '{query}' 장소명이 없습니다."
            )
        if place_headers.get("x-place-search-source") != "kakao-rest":
            raise RuntimeError("Kakao 장소 검색이 demo 공급자로 대체되었습니다.")
        lat = selected.get("lat")
        lng = selected.get("lng")
        if (
            isinstance(lat, bool)
            or not isinstance(lat, (int, float))
            or not math.isfinite(lat)
            or isinstance(lng, bool)
            or not isinstance(lng, (int, float))
            or not math.isfinite(lng)
        ):
            raise RuntimeError(
                f"Kakao 장소 검색 결과의 '{query}' 좌표가 올바르지 않습니다."
            )
        selected_places[query] = {
            "id": str(selected.get("id") or f"deploy-{query}"),
            "name": str(selected.get("name") or query),
            "lat": lat,
            "lng": lng,
        }
    return selected_places


def _fresh_observation(value: object, label: str) -> None:
    if not isinstance(value, str):
        raise RuntimeError(f"{label} 관측시각이 없습니다.")
    try:
        observed_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"{label} 관측시각 형식이 올바르지 않습니다.") from exc
    if observed_at.tzinfo is None:
        raise RuntimeError(f"{label} 관측시각에 시간대가 없습니다.")
    age_seconds = (
        datetime.now(UTC) - observed_at.astimezone(UTC)
    ).total_seconds()
    if age_seconds < -300:
        raise RuntimeError(f"{label} 관측시각이 현재보다 미래입니다.")
    if age_seconds > 3 * 60 * 60:
        raise RuntimeError(f"{label} 관측값이 3시간보다 오래됐습니다.")


def verify_weather(weather: object) -> None:
    if not isinstance(weather, dict):
        raise RuntimeError("실시간 날씨 응답 계약이 올바르지 않습니다.")
    _fresh_observation(weather.get("observedAt"), "실시간 날씨")
    _fresh_observation(
        weather.get("airQualityObservedAt"),
        "실시간 대기질",
    )


def verify_homepage_security(
    headers: dict[str, str],
    *,
    require_hsts: bool = True,
) -> None:
    if headers.get("x-content-type-options") != "nosniff":
        raise RuntimeError("/: Nginx 보안 헤더가 적용되지 않았습니다.")
    hsts = headers.get("strict-transport-security", "")
    if require_hsts and "max-age=" not in hsts.lower():
        raise RuntimeError("/: HSTS 보안 헤더가 적용되지 않았습니다.")
    if "nginx/" in headers.get("server", "").lower():
        raise RuntimeError("/: Server 헤더가 Nginx 버전을 노출합니다.")


def verify_readiness(
    readiness: object,
    *,
    allow_local_gaps: bool,
    is_local_http: bool,
) -> None:
    if isinstance(readiness, dict) and readiness.get("ready") is True:
        return
    raw_missing = readiness.get("missing", []) if isinstance(readiness, dict) else []
    missing = {
        str(item)
        for item in raw_missing
        if isinstance(item, str) and item
    } if isinstance(raw_missing, list) else set()
    if (
        allow_local_gaps
        and is_local_http
        and missing
        and missing.issubset(LOCAL_ONLY_READINESS_GAPS)
    ):
        return
    raise RuntimeError(
        f"/api/readiness: 운영 설정 미완료 ({', '.join(sorted(missing))})"
    )


def verify_recommended_routes(routes: object, *, requested_top_n: int) -> None:
    """공급자가 반환한 실제 후보 범위에서 추천 응답 계약을 확인한다."""
    if (
        not isinstance(routes, list)
        or not routes
        or len(routes) > requested_top_n
    ):
        raise RuntimeError(
            "실경로 추천이 요청 범위 안의 실제 후보를 반환하지 않았습니다."
        )
    route_ids = [
        str(item.get("route", {}).get("id") or "")
        for item in routes
        if isinstance(item, dict)
    ]
    if len(route_ids) != len(routes) or "" in route_ids or len(set(route_ids)) != len(routes):
        raise RuntimeError("실경로 추천 ID가 없거나 중복됐습니다.")
    scores = [
        item.get("score", {}).get("finalScore")
        for item in routes
        if isinstance(item, dict)
    ]
    if (
        len(scores) != len(routes)
        or any(
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(score)
            or not 0 <= score <= 100
            for score in scores
        )
        or scores != sorted(scores, reverse=True)
    ):
        raise RuntimeError("실경로 추천 점수가 내림차순이 아닙니다.")
    for item in routes:
        route = item.get("route", {})
        path = route.get("path")
        if not isinstance(path, list) or len(path) < 2:
            raise RuntimeError("실경로 geometry가 없습니다.")
        if route.get("geometryQuality") not in {"exact", "mixed"}:
            raise RuntimeError("실경로 geometry 품질이 실측 경로 계약과 다릅니다.")
        terrain = route.get("terrain")
        if (
            not isinstance(terrain, dict)
            or terrain.get("status") != "estimated_90m"
        ):
            raise RuntimeError("90m DEM 경사도 계산 결과가 없습니다.")
        shade = route.get("shade", {})
        if not isinstance(shade, dict):
            raise RuntimeError("VWorld 건물 기반 주간 그늘 계산이 완료되지 않았습니다.")
        shade_ratio = shade.get("shadeRatio")
        if (
            shade.get("status") != "estimated_public"
            or shade.get("dataQuality") != "public"
            or isinstance(shade_ratio, bool)
            or not isinstance(shade_ratio, (int, float))
            or not math.isfinite(shade_ratio)
            or not 0 <= shade_ratio <= 1
        ):
            raise RuntimeError("VWorld 건물 기반 주간 그늘 계산이 완료되지 않았습니다.")
        score_kind = item.get("score", {}).get("scoreKind")
        if score_kind not in {
            "rule_baseline",
            "bootstrap_baseline",
            "human_model",
        }:
            raise RuntimeError("검증된 추천 모델 tier가 운영 응답에 포함되지 않았습니다.")


def verify(base: str, *, allow_local_readiness_gaps: bool = False) -> None:
    scheme, hostname, _ = _validated_base(base)
    is_local_http = (
        scheme == "http"
        and hostname in {"localhost", "127.0.0.1", "::1"}
    )
    homepage, homepage_headers = request(base, "/")
    if not isinstance(homepage, str) or "부산 접근성 길찾기" not in homepage:
        raise RuntimeError("/: 운영 프론트 문서를 확인할 수 없습니다.")
    if f'{base}/og-route-preview.png' not in homepage:
        raise RuntimeError("/: 소셜 미리보기 URL이 배포 origin으로 치환되지 않았습니다.")
    verify_homepage_security(
        homepage_headers,
        require_hsts=scheme == "https",
    )

    manifest, _ = request(base, "/manifest.webmanifest")
    if not isinstance(manifest, dict) or manifest.get("display") != "standalone":
        raise RuntimeError("/manifest.webmanifest: 설치형 PWA 계약이 올바르지 않습니다.")
    service_worker, _ = request(base, "/sw.js")
    if not isinstance(service_worker, str) or "workbox" not in service_worker:
        raise RuntimeError("/sw.js: 서비스 워커를 확인할 수 없습니다.")

    readiness, _ = request(base, "/api/readiness")
    verify_readiness(
        readiness,
        allow_local_gaps=allow_local_readiness_gaps,
        is_local_http=is_local_http,
    )

    places = verify_places(base)

    weather, _ = request(base, "/api/weather")
    verify_weather(weather)

    stops, _ = request(base, f"/api/bus/stops?{urlencode({'q': '서면'})}")
    if (
        not isinstance(stops, list)
        or not stops
        or not any(
            isinstance(stop, dict)
            and "서면" in str(stop.get("stopName") or "")
            for stop in stops
        )
    ):
        raise RuntimeError("부산 버스 정류장 실검색 결과가 올바르지 않습니다.")

    departure = datetime.now(ZoneInfo("Asia/Seoul")).replace(
        hour=13, minute=0, second=0, microsecond=0
    ).isoformat()
    routes, _ = request(
        base,
        "/api/routes/recommend",
        {
            "origin": places["북구청"],
            "destination": places["부산역"],
            "profile": "general",
            "weatherScenario": "normal",
            "options": {"departureAt": departure},
            "topN": 3,
        },
    )
    verify_recommended_routes(routes, requested_top_n=3)

    print("배포 스모크 검증 완료: PWA, 보안 헤더, 장소, 날씨, 버스, 실경로, 경사도, 그늘")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8080", help="배포된 서비스 origin")
    parser.add_argument(
        "--allow-local-readiness-gaps",
        action="store_true",
        help=(
            "localhost HTTP에서만 origin_security와 kakao_login 누락을 허용합니다. "
            "공개 배포 검증에는 사용하지 않습니다."
        ),
    )
    args = parser.parse_args()
    try:
        verify(
            args.base.rstrip("/"),
            allow_local_readiness_gaps=args.allow_local_readiness_gaps,
        )
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(f"배포 스모크 검증 실패: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
