"""점수 → 추천 이유/주의사항/음성 요약/저상버스 상태 생성. 프론트 explain.ts 와 동일."""
from __future__ import annotations

from ..models import LowFloorStatus, RouteCandidate, ScoreComponents, WeatherCondition


def derive_low_floor_status(r: RouteCandidate) -> LowFloorStatus:
    buses = [s for s in r.segments if s.mode == "bus"]
    if not buses:
        return "none"
    if any(s.is_low_floor_bus is False for s in buses):
        return "regular"
    if all(s.is_low_floor_bus is True for s in buses):
        return "confirmed"
    return "unknown"


def build_reasons(r: RouteCandidate, c: ScoreComponents, low_floor: LowFloorStatus) -> list[str]:
    out: list[str] = []
    has_vertical = any(s.needs_vertical_move for s in r.segments)

    if c.time_efficiency is not None and c.time_efficiency >= 90:
        out.append("후보 중 소요시간이 가장 짧은 편이에요.")
    if c.walk_comfort is not None and c.walk_comfort >= 80:
        out.append(f"도보가 {int(r.total_walk_m)}m로 보행 부담이 적어요.")
    if has_vertical and c.elevator is not None and c.elevator >= 90:
        out.append("승강기로 이동할 수 있어 계단을 피할 수 있어요.")
    constrained_walk = [s for s in r.segments if s.mode == "walk"]
    if constrained_walk and all(
        segment.wheelchair_constraints_applied is True
        for segment in constrained_walk
    ):
        out.append("기록된 계단·노면·폭·턱·경사 제한을 적용한 경로예요.")
    if low_floor == "confirmed":
        out.append("경로의 버스가 저상버스로 확인됐어요.")
    if c.safety is not None and c.safety >= 85:
        out.append("횡단과 환승 부담이 낮은 편이에요.")
    if c.weather_safety is not None and c.weather_safety >= 85:
        out.append("현재 날씨 조건에서 비교적 안전해요.")
    if r.transfer_count == 0:
        out.append("환승 없이 한 번에 이동해요.")

    if not out:
        out.append("확인된 정보 범위에서 경로를 비교했어요.")
    return out[:4]


def build_cautions(
    r: RouteCandidate, c: ScoreComponents, low_floor: LowFloorStatus, w: WeatherCondition
) -> list[str]:
    out: list[str] = []

    stair_no_elev = any(
        (s.has_stairs or s.needs_vertical_move) and s.has_elevator is not True for s in r.segments
    )
    if stair_no_elev and c.elevator is not None and c.elevator < 70:
        out.append("계단 구간이 있어 수직 이동 시 유의해 주세요.")

    if low_floor == "regular":
        out.append("일반버스 이용 노선이 포함되어 있습니다.")

    weather_risk = (
        100 - c.weather_safety
        if c.weather_safety is not None
        else None
    )
    if weather_risk is not None and weather_risk >= 35:
        if w.is_heatwave:
            out.append("폭염 시 야외 보행 수분 섭취에 유의해 주세요.")
        elif w.is_coldwave:
            out.append("한파 시 따뜻한 보온 복장을 권장해 드려요.")
        if w.sky == "rain" or w.precipitation_mm > 0:
            out.append("우천 시 안전한 보행 이동에 유의해 주세요.")
        if w.air in ("bad", "very_bad"):
            out.append("미세먼지 수준에 맞춰 마스크 착용을 권장해 드려요.")

    walk_segments = [s for s in r.segments if s.mode == "walk"]
    crosswalks = (
        sum(s.crosswalk_count for s in walk_segments if s.crosswalk_count is not None)
        if walk_segments
        and all(s.crosswalk_count is not None for s in walk_segments)
        else None
    )
    if crosswalks is not None and crosswalks >= 4:
        out.append(f"횡단보도 {crosswalks}곳을 경유하여 이동해요.")

    if c.data_reliability is not None and c.data_reliability < 70:
        out.append("실시간 교통 환경에 따라 차이가 있을 수 있어요.")

    if any(
        segment.wheelchair_constraints_applied is True
        for segment in r.segments
        if segment.mode == "walk"
    ):
        out.append(
            "지도에 없는 공사·적치물·고장 등 임시 장애물은 출발 전에 확인해 주세요."
        )

    return out[:4]


def build_voice_summary(
    r: RouteCandidate, rank: int, low_floor: LowFloorStatus, top_caution: str | None = None
) -> str:
    lf = {
        "confirmed": "저상버스 이용 가능",
        "regular": "일반버스 포함",
        "unknown": "대중교통 이용",
        "none": "버스 미이용",
    }[low_floor]
    s = (
        f"{rank}번 경로, {r.summary}. 예상 {int(r.total_duration_min)}분, "
        f"도보 {int(r.total_walk_m)}미터, 환승 {r.transfer_count}회. {lf}."
    )
    if top_caution:
        s += f" 주의: {top_caution}"
    return s
