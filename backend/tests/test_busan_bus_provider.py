import asyncio

from defusedxml import ElementTree

import pytest

import app.providers.busan_bus as provider
from app.providers.busan_bus import _arrival, _parse_root


def test_parses_official_low_floor_arrival_contract():
    item = ElementTree.fromstring("""
      <item><lineno>81</lineno><carno1>5217</carno1><min1>5</min1>
      <station1>2</station1><lowplate1>1</lowplate1></item>
    """)
    result = _arrival(item, "1")
    assert result is not None
    assert result.route_name == "81"
    assert result.vehicle_no == "5217"
    assert result.arrival_min == 5
    assert result.remaining_stops == 2
    assert result.is_low_floor is True


def test_preserves_non_numeric_arrival_status_and_unknown_low_floor():
    item = ElementTree.fromstring("""
      <item><lineno>1010</lineno><carno2>5201</carno2><min2>운행대기</min2>
      <station2></station2><lowplate2>9</lowplate2></item>
    """)
    result = _arrival(item, "2")
    assert result is not None
    assert result.arrival_min is None
    assert result.arrival_message == "운행대기"
    assert result.remaining_stops is None
    assert result.is_low_floor is None


def test_rejects_negative_arrival_metrics_instead_of_exposing_them():
    item = ElementTree.fromstring("""
      <item><lineno>81</lineno><carno1>5217</carno1><min1>-1</min1>
      <station1>2</station1><lowplate1>1</lowplate1></item>
    """)
    with pytest.raises(RuntimeError, match="음수 도착 지표"):
        _arrival(item, "1")


def test_rejects_bims_error_response():
    with pytest.raises(RuntimeError, match="SERVICE_KEY_IS_NOT_REGISTERED_ERROR"):
        _parse_root(b"<response><header><resultCode>30</resultCode><resultMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</resultMsg></header></response>")


def test_rejects_xml_external_entity_payload():
    payload = b"""<?xml version="1.0"?>
    <!DOCTYPE response [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
    <response>
      <header>
        <resultCode>00</resultCode>
        <resultMsg>&xxe;</resultMsg>
      </header>
    </response>"""
    with pytest.raises(RuntimeError, match="안전한 형식"):
        _parse_root(payload)


def test_matches_tmap_stop_to_local_bims_index_without_external_lookup(monkeypatch):
    monkeypatch.setattr(provider, "_BUS_STOPS", (
        provider._LocalBusStop(
            "505790000", "시청", "01001", 35.1798, 129.0751, "시청"
        ),
        provider._LocalBusStop(
            "505790100", "시청", "01002", 35.1850, 129.0800, "시청"
        ),
    ))

    async def fail_request(*_args, **_kwargs):
        raise AssertionError("정류소 매칭 중 외부 API를 호출했습니다.")

    monkeypatch.setattr(provider, "_request", fail_request)
    result = asyncio.run(provider.find_bus_stop_candidates(
        "시청", lat=35.1797, lng=129.0750
    ))

    assert [item.stop_id for item in result] == ["505790000"]
