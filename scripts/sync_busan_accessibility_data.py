"""DECO 키로 접근 가능한 부산 장애인 편의시설 원본을 수집한다.

관광지 장애인 편의시설 API는 위치구분·편의시설 종류를 제공하지만 좌표를
제공하지 않는다. 따라서 이 스크립트의 결과는 ``data/da/raw``에 원본으로
보관하며, 좌표가 있는 보행 경로 레이어나 ``hasSlope``로 추정 변환하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
TOURISM_ENDPOINT = (
    "https://apis.data.go.kr/6260000/BusanFcltsDsgstInfoService/"
    "getFcltsDsgstInfo"
)
DEFAULT_OUTPUT = ROOT / "data" / "da" / "raw" / "busan_tourism_accessibility_api.json"


def read_env_file(path: Path) -> dict[str, str]:
    """비밀값을 출력하지 않고 단순 KEY=VALUE 환경파일을 읽는다."""
    if not path.is_file():
        raise FileNotFoundError(f"환경파일이 없습니다: {path}")
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def resolve_decoding_key(env_values: dict[str, str]) -> str:
    """DECO를 우선하고 이전 표준 변수는 호환용으로만 사용한다."""
    key = os.environ.get("DECO") or env_values.get("DECO")
    key = key or os.environ.get("DATA_GO_KR_SERVICE_KEY")
    key = key or env_values.get("DATA_GO_KR_SERVICE_KEY", "")
    if not key:
        raise RuntimeError("DECO 또는 DATA_GO_KR_SERVICE_KEY가 설정되지 않았습니다.")
    if "%" in key:
        raise RuntimeError("URL Decoding 키가 필요합니다. INCO를 사용하지 마세요.")
    return key


def _request_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=30) as response:  # nosec B310: fixed HTTPS API
        body = response.read()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("관광지 장애인 편의시설 API가 JSON을 반환하지 않았습니다.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("관광지 장애인 편의시설 API 응답이 객체가 아닙니다.")
    return payload


def fetch_tourism_accessibility(key: str, *, page_size: int = 100) -> list[dict[str, Any]]:
    """전 페이지를 받아 항목·총건수 계약을 검증한다."""
    if not 1 <= page_size <= 1000:
        raise ValueError("page_size는 1~1000이어야 합니다.")
    records: list[dict[str, Any]] = []
    page = 1
    total: int | None = None
    while total is None or len(records) < total:
        query = urlencode({
            "ServiceKey": key,
            "pageNo": page,
            "numOfRows": page_size,
            "resultType": "json",
        })
        payload = _request_json(f"{TOURISM_ENDPOINT}?{query}")
        response = payload.get("response")
        if not isinstance(response, dict):
            raise RuntimeError("관광지 장애인 편의시설 API response 객체가 없습니다.")
        header = response.get("header")
        body = response.get("body")
        if not isinstance(header, dict) or header.get("resultCode") != "00":
            raise RuntimeError(f"관광지 장애인 편의시설 API 오류: {header}")
        if not isinstance(body, dict):
            raise RuntimeError("관광지 장애인 편의시설 API body 객체가 없습니다.")
        items = body.get("items")
        if isinstance(items, dict):
            items = items.get("item", [])
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise RuntimeError("관광지 장애인 편의시설 API item 배열이 올바르지 않습니다.")
        page_total = body.get("totalCount")
        try:
            parsed_total = int(page_total)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("관광지 장애인 편의시설 API totalCount가 숫자가 아닙니다.") from exc
        if parsed_total < 0 or (total is not None and total != parsed_total):
            raise RuntimeError("관광지 장애인 편의시설 API totalCount가 페이지마다 일관되지 않습니다.")
        total = parsed_total
        records.extend(items)
        if not items and len(records) < total:
            raise RuntimeError("총건수에 도달하기 전에 관광지 장애인 편의시설 페이지가 비었습니다.")
        page += 1
    if len(records) != total:
        raise RuntimeError("관광지 장애인 편의시설 수집 건수가 totalCount와 다릅니다.")
    return records


def write_snapshot(output: Path, records: list[dict[str, Any]]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "source": "https://www.data.go.kr/data/15034043/openapi.do",
        "recordCount": len(records),
        "coordinateStatus": "not_provided_by_api",
        "records": records,
    }
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump(snapshot, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    try:
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.production")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--page-size", type=int, default=100)
    args = parser.parse_args()

    key = resolve_decoding_key(read_env_file(args.env_file))
    records = fetch_tourism_accessibility(key, page_size=args.page_size)
    write_snapshot(args.output, records)
    print(f"관광지 장애인 편의시설 원본 수집 완료: {len(records)}건")


if __name__ == "__main__":
    main()
