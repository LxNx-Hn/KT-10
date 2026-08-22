import pytest

from app.providers.busan_subway_stations import (
    LINE_STATIONS,
    journey_direction,
    public_station_name,
    resolve_line,
)


def test_verified_line_station_counts_and_endpoints():
    assert {line: len(stations) for line, stations in LINE_STATIONS.items()} == {
        "1": 40,
        "2": 43,
        "3": 17,
        "4": 14,
    }
    assert LINE_STATIONS["1"][:2] == ("다대포해수욕장", "다대포항")
    assert LINE_STATIONS["1"][-2:] == ("범어사", "노포")
    assert LINE_STATIONS["2"][:2] == ("장산", "중동")
    assert LINE_STATIONS["2"][-2:] == ("남양산", "양산")
    assert LINE_STATIONS["3"][:2] == ("수영", "망미")
    assert LINE_STATIONS["3"][-2:] == ("체육공원", "대저")
    assert LINE_STATIONS["4"][:2] == ("미남", "동래")
    assert LINE_STATIONS["4"][-2:] == ("고촌", "안평")


@pytest.mark.parametrize(
    ("station", "line", "expected"),
    [
        ("서면역", "1", "서면(1)"),
        ("서면", "2", "서면(2)"),
        ("수영", "3", "수영(3)"),
        ("동래", "4", "동래(4)"),
        ("시청역", "1", "시청"),
    ],
)
def test_public_station_names_are_line_specific(station, line, expected):
    assert public_station_name(station, line) == expected


def test_line_resolution_prefers_provider_route_id_and_rejects_mismatch():
    assert resolve_line("시청", "서면", "71") == "1"
    assert resolve_line("서면", "전포", "72") == "2"
    assert resolve_line("연산", "물만골", "73") == "3"
    assert resolve_line("동래", "미남", "74") == "4"
    with pytest.raises(ValueError, match="일치하지"):
        resolve_line("시청", "서면", "72")


def test_line_resolution_without_route_id_requires_one_common_line():
    assert resolve_line("부산역", "서면역") == "1"
    with pytest.raises(ValueError, match="하나로 확정"):
        resolve_line("서면", "서면")


@pytest.mark.parametrize(
    ("start", "end", "line", "expected"),
    [
        ("시청", "서면", "1", "0"),
        ("서면", "시청", "1", "1"),
        ("서면", "전포", "2", "0"),
        ("연산", "물만골", "3", "0"),
        ("동래", "미남", "4", "0"),
    ],
)
def test_journey_direction_matches_verified_public_timetable(
    start,
    end,
    line,
    expected,
):
    assert journey_direction(start, end, line) == expected
