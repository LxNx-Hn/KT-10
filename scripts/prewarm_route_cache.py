"""우선 검증 OD의 OSM 경사·VWorld 건물 캐시를 배포 전에 준비한다."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OD_FILE = ROOT / "data" / "precompute" / "priority_od_pairs.json"


def _json_request(
    url: str,
    *,
    payload: dict | None = None,
    timeout: float = 30,
) -> tuple[object, dict[str, str]]:
    request = Request(
        url,
        data=(
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if payload is not None
            else None
        ),
        headers={"Content-Type": "application/json"} if payload is not None else {},
        method="POST" if payload is not None else "GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return (
                json.load(response),
                {key.lower(): value for key, value in response.headers.items()},
            )
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("detail")
        except (ValueError, UnicodeDecodeError, AttributeError):
            detail = None
        raise RuntimeError(
            f"{url} 호출 실패: HTTP {exc.code}"
            + (f" ({detail})" if isinstance(detail, str) else "")
        ) from exc
    except (TimeoutError, URLError) as exc:
        raise RuntimeError(f"{url} 연결 실패") from exc


def _place(base_url: str, query: str) -> dict:
    data, headers = _json_request(
        f"{base_url}/api/places/search?q={quote(query)}"
    )
    if headers.get("x-place-search-source") != "kakao-rest":
        raise RuntimeError(f"{query}: Kakao REST 장소 출처를 확인할 수 없습니다.")
    if not isinstance(data, list) or not data:
        raise RuntimeError(f"{query}: 장소 검색 결과가 없습니다.")
    place = data[0]
    if not isinstance(place, dict):
        raise RuntimeError(f"{query}: 장소 검색 응답 형식이 올바르지 않습니다.")
    return place


def _recommend(base_url: str, origin: dict, destination: dict) -> tuple[list, float]:
    started = time.perf_counter()
    data, _ = _json_request(
        f"{base_url}/api/routes/recommend",
        payload={
            "origin": origin,
            "destination": destination,
            "profile": "general",
            "weatherScenario": "normal",
            "options": {},
            "topN": 3,
        },
    )
    elapsed = time.perf_counter() - started
    if not isinstance(data, list) or not data:
        raise RuntimeError("경로 추천 응답에 후보가 없습니다.")
    return data, elapsed


def _quality(routes: list) -> dict:
    route_rows = [
        item.get("route") or {}
        for item in routes
        if isinstance(item, dict)
    ]
    return {
        "routeCount": len(route_rows),
        "exactGeometryCount": sum(
            route.get("geometryQuality") == "exact"
            for route in route_rows
        ),
        "terrainReadyCount": sum(
            (route.get("terrain") or {}).get("status") == "estimated_90m"
            for route in route_rows
        ),
        "shadeReadyCount": sum(
            (route.get("shade") or {}).get("status")
            in {"estimated_public", "not_daylight"}
            for route in route_rows
        ),
    }


def prewarm_pair(
    base_url: str,
    origin_query: str,
    destination_query: str,
    *,
    max_wait_seconds: float,
    poll_seconds: float,
    max_cached_seconds: float,
) -> dict:
    origin = _place(base_url, origin_query)
    destination = _place(base_url, destination_query)
    deadline = time.monotonic() + max_wait_seconds
    attempts = 0
    latest_quality: dict = {}
    while True:
        attempts += 1
        try:
            routes, elapsed = _recommend(base_url, origin, destination)
        except RuntimeError as exc:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"{origin_query} -> {destination_query}: 사전계산 중 "
                    f"공급자 오류가 반복됐습니다. ({exc})"
                ) from exc
            time.sleep(poll_seconds)
            continue
        latest_quality = _quality(routes)
        if (
            latest_quality["routeCount"] > 0
            and latest_quality["exactGeometryCount"]
            == latest_quality["routeCount"]
            and latest_quality["terrainReadyCount"]
            == latest_quality["routeCount"]
            and latest_quality["shadeReadyCount"]
            == latest_quality["routeCount"]
        ):
            cached_routes, cached_elapsed = _recommend(
                base_url,
                origin,
                destination,
            )
            cached_quality = _quality(cached_routes)
            if cached_elapsed > max_cached_seconds:
                raise RuntimeError(
                    f"{origin_query} -> {destination_query}: 캐시 응답 "
                    f"{cached_elapsed:.2f}초가 한도 {max_cached_seconds:.2f}초를 초과했습니다."
                )
            return {
                "origin": origin.get("name"),
                "destination": destination.get("name"),
                "attempts": attempts,
                "warmResponseSeconds": round(elapsed, 2),
                "cachedResponseSeconds": round(cached_elapsed, 2),
                **cached_quality,
            }
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"{origin_query} -> {destination_query}: 사전계산 시간 초과 "
                f"({json.dumps(latest_quality, ensure_ascii=False)})"
            )
        time.sleep(poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--od-file", type=Path, default=DEFAULT_OD_FILE)
    parser.add_argument("--max-wait-seconds", type=float, default=180)
    parser.add_argument("--poll-seconds", type=float, default=5)
    parser.add_argument("--max-cached-seconds", type=float, default=10)
    parser.add_argument(
        "--limit",
        type=int,
        help="우선순위 파일의 앞 N개 OD만 사전계산한다.",
    )
    args = parser.parse_args()
    pairs = json.loads(args.od_file.read_text(encoding="utf-8"))
    if not isinstance(pairs, list) or not pairs:
        raise SystemExit("사전계산 OD 파일이 비어 있거나 배열이 아닙니다.")
    if args.limit is not None:
        if args.limit < 1:
            raise SystemExit("--limit은 1 이상이어야 합니다.")
        pairs = pairs[:args.limit]
    results = []
    for pair in pairs:
        if not isinstance(pair, dict):
            raise SystemExit("사전계산 OD 항목이 객체가 아닙니다.")
        results.append(prewarm_pair(
            args.base_url.rstrip("/"),
            str(pair["originQuery"]),
            str(pair["destinationQuery"]),
            max_wait_seconds=args.max_wait_seconds,
            poll_seconds=args.poll_seconds,
            max_cached_seconds=args.max_cached_seconds,
        ))
    print(json.dumps({"status": "ok", "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
