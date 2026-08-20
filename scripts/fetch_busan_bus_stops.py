"""공식 부산 BIMS 정류소 목록을 서비스용 로컬 인덱스로 고정한다."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

BASE_URL = "https://apis.data.go.kr/6260000/BusanBIMS/busStopList"
PAGE_SIZE = 1000


def _text(item: ET.Element, name: str) -> str:
    return (item.findtext(name) or "").strip()


def _page(service_key: str, page_no: int) -> tuple[list[dict], int]:
    query = urllib.parse.urlencode({
        "serviceKey": service_key,
        "pageNo": page_no,
        "numOfRows": PAGE_SIZE,
    })
    request = urllib.request.Request(f"{BASE_URL}?{query}")
    with urllib.request.urlopen(request, timeout=30) as response:
        root = ET.fromstring(response.read())
    if root.findtext(".//resultCode") != "00":
        raise RuntimeError(root.findtext(".//resultMsg") or "BIMS 오류")
    rows: list[dict] = []
    for item in root.findall(".//item"):
        try:
            lat = float(_text(item, "gpsy"))
            lng = float(_text(item, "gpsx"))
        except ValueError:
            continue
        stop_id = _text(item, "bstopid")
        name = _text(item, "bstopnm")
        if stop_id and name:
            rows.append({
                "id": stop_id,
                "name": name,
                "arsNo": _text(item, "arsno") or None,
                "lat": lat,
                "lng": lng,
            })
    return rows, int(root.findtext(".//totalCount") or 0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service-key", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/ai/busan_bus_stops.json"),
    )
    args = parser.parse_args()

    rows: list[dict] = []
    page_no = 1
    total_count = 0
    while page_no == 1 or len(rows) < total_count:
        page_rows, total_count = _page(args.service_key, page_no)
        if not page_rows:
            break
        rows.extend(page_rows)
        page_no += 1
    unique = {row["id"]: row for row in rows}
    if len(unique) != total_count:
        raise RuntimeError(
            f"BIMS 정류소 전체 건수 불일치: expected={total_count}, actual={len(unique)}"
        )
    payload = {
        "source": BASE_URL,
        "fetchedAt": datetime.now(UTC).isoformat(),
        "count": len(unique),
        "stops": sorted(unique.values(), key=lambda row: row["id"]),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"wrote {len(unique)} stops to {args.output}")


if __name__ == "__main__":
    main()
