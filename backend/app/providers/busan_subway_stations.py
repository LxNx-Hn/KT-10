"""부산교통공사 도시철도 1~4호선 정적 역 계약.

역 순서는 ``data/raw/busan_subway_station_convenience_20251231.csv``의
2025-12-31 스냅샷을 개발 단계에서 검증해 UTF-8 코드로 고정했다.
중복 역의 공공 운행시각표 ``sname`` 규칙과 ``updown`` 방향은
2026-08-22 실제 B551542 ``getTrainTime`` 응답으로 교차 확인했다.
"""
from __future__ import annotations

import re


ROUTE_ID_TO_LINE = {
    "71": "1",
    "72": "2",
    "73": "3",
    "74": "4",
}

LINE_STATIONS: dict[str, tuple[str, ...]] = {
    "1": (
        "다대포해수욕장", "다대포항", "낫개", "신장림", "장림", "동매", "신평", "하단",
        "당리", "사하", "괴정", "대티", "서대신", "동대신", "토성", "자갈치", "남포", "중앙",
        "부산", "초량", "부산진", "좌천", "범일", "범내골", "서면", "부전", "양정", "시청",
        "연산", "교대", "동래", "명륜", "온천장", "부산대", "장전", "구서", "두실", "남산",
        "범어사", "노포",
    ),
    "2": (
        "장산", "중동", "해운대", "동백", "벡스코", "센텀시티", "민락", "수영", "광안", "금련산",
        "남천", "경성대.부경대", "대연", "못골", "지게골", "문현", "국제금융센터.부산은행", "전포",
        "서면", "부암", "가야", "동의대", "개금", "냉정", "주례", "감전", "사상", "덕포", "모덕", "모라",
        "구남", "구명", "덕천", "수정", "화명", "율리", "동원", "금곡", "호포", "증산",
        "부산대양산캠퍼스", "남양산", "양산",
    ),
    "3": (
        "수영", "망미", "배산", "물만골", "연산", "거제", "종합운동장", "사직", "미남", "만덕",
        "남산정", "숙등", "덕천", "구포", "강서구청", "체육공원", "대저",
    ),
    "4": (
        "미남", "동래", "수안", "낙민", "충렬사", "명장", "서동", "금사", "반여농산물시장",
        "석대", "영산대", "윗반송", "고촌", "안평",
    ),
}

_DUPLICATE_STATIONS = {
    station
    for line, stations in LINE_STATIONS.items()
    for station in stations
    if sum(station in other for other in LINE_STATIONS.values()) > 1
}
_LINE_SUFFIX = re.compile(r"\(([1-4])\)$")


def station_base(value: str | None) -> str:
    """역 접미사와 공공데이터 호선 접미사만 제거한다."""
    cleaned = (value or "").strip()
    if len(cleaned) > 1 and cleaned.endswith("역"):
        cleaned = cleaned[:-1]
    return _LINE_SUFFIX.sub("", cleaned).strip()


def line_from_route_id(route_id: object) -> str | None:
    if route_id is None:
        return None
    text = str(route_id).strip()
    if text in LINE_STATIONS:
        return text
    return ROUTE_ID_TO_LINE.get(text)


def resolve_line(
    start_station_name: str,
    end_station_name: str,
    route_id: object = None,
) -> str:
    """명시 노선을 우선하고, 없으면 두 역의 유일 공통 노선만 허용한다."""
    explicit = line_from_route_id(route_id)
    start = station_base(start_station_name)
    end = station_base(end_station_name)
    if explicit is not None:
        if start not in LINE_STATIONS[explicit] or end not in LINE_STATIONS[explicit]:
            raise ValueError("명시된 노선과 승·하차역이 일치하지 않습니다.")
        return explicit
    matching = [
        line
        for line, stations in LINE_STATIONS.items()
        if start in stations and end in stations and start != end
    ]
    if len(matching) != 1:
        raise ValueError("승·하차역의 도시철도 노선을 하나로 확정할 수 없습니다.")
    return matching[0]


def public_station_name(station_name: str, line: str) -> str:
    base = station_base(station_name)
    if line not in LINE_STATIONS or base not in LINE_STATIONS[line]:
        raise ValueError("노선에 해당하는 역을 확인할 수 없습니다.")
    return f"{base}({line})" if base in _DUPLICATE_STATIONS else base


def journey_direction(
    start_station_name: str,
    end_station_name: str,
    line: str,
) -> str:
    stations = LINE_STATIONS[line]
    start_index = stations.index(station_base(start_station_name))
    end_index = stations.index(station_base(end_station_name))
    if start_index == end_index:
        raise ValueError("승차역과 하차역이 같습니다.")
    # 실제 운행시각표 교차 확인: 역 순서 감소=0, 증가=1.
    return "1" if end_index > start_index else "0"
