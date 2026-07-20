"""
ODsay API 라이브 테스트. 실제 네트워크 호출로 API 키/파싱을 검증한다.
실행 (ai/ 에서): pytest tests/test_odsay_live.py -v -s
"""
import asyncio

from collectors.odsay_collector import OdsayRouteCollector
from collectors.base import Coordinate
from api.router import _parse_api_features

# 부산진구청 → 서면역 (부산 테스트 좌표)
ORIGIN = Coordinate(lat=35.1626, lng=129.0530)
DEST = Coordinate(lat=35.1578, lng=129.0594)


def test_odsay_returns_candidates():
    """ODsay가 경로 후보를 최소 1개 이상 반환해야 한다."""
    collector = OdsayRouteCollector()
    candidates = asyncio.run(collector.collect(ORIGIN, DEST))

    print(f"\n수집된 경로 수: {len(candidates)}")
    for i, c in enumerate(candidates):
        print(f"  경로 {i + 1}: {len(c.path)}개 좌표, {c.duration_min}분, {c.distance_m}m")
        info = (c.raw_response or {}).get("info", {})
        print(f"    환승: {info.get('transferCount', 0)}회")
        print(f"    도보: {info.get('totalWalk', 0)}m")

    assert len(candidates) > 0, "ODsay 응답이 비어있음 — API 키 또는 네트워크 확인"
    assert len(candidates[0].path) >= 2, "경로 좌표가 2개 미만"


def test_odsay_no_auth_error():
    """응답에 ApiKeyAuthFailed 오류가 없어야 한다."""
    collector = OdsayRouteCollector()
    candidates = asyncio.run(collector.collect(ORIGIN, DEST))

    if not candidates:
        raise AssertionError(
            "경로 수집 실패 — 콘솔에서 [ODsay] 에러 메시지 확인 "
            "(ApiKeyAuthFailed 또는 네트워크 오류)"
        )


def test_parse_api_features():
    """raw_response에서 피처가 올바르게 파싱되는지 확인한다."""
    collector = OdsayRouteCollector()
    candidates = asyncio.run(collector.collect(ORIGIN, DEST))

    if not candidates:
        import pytest
        pytest.skip("ODsay 응답 없음 — 피처 파싱 테스트 건너뜀")

    feats = _parse_api_features(candidates[0])

    print("\n파싱된 피처:")
    for k, v in feats.items():
        print(f"  {k}: {v}")

    assert "transfer_count" in feats
    assert "walk_distance_m" in feats
    assert "is_low_floor_bus" in feats
    assert "elevator_ratio" in feats
    assert isinstance(feats["transfer_count"], int)
    assert feats["walk_distance_m"] >= 0
    assert feats["is_low_floor_bus"] in (0, 1)
    assert 0.0 <= feats["elevator_ratio"] <= 1.0
