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

    if c.time_efficiency >= 90:
        out.append("후보 중 소요시간이 가장 짧은 편이에요.")
    if c.walk_comfort >= 80:
        out.append(f"도보가 {int(r.total_walk_m)}m로 보행 부담이 적어요.")
    if has_vertical and c.elevator >= 90:
        out.append("승강기로 이동할 수 있어 계단을 피할 수 있어요.")
    if low_floor == "confirmed":
        out.append("경로의 버스가 저상버스로 확인됐어요.")
    if c.safety >= 85:
        out.append("횡단과 환승 부담이 낮은 편이에요.")
    if c.weather_safety >= 85:
        out.append("현재 날씨 조건에서 비교적 안전해요.")
    if r.transfer_count == 0:
        out.append("환승 없이 한 번에 이동해요.")

    if not out:
        out.append("균형 잡힌 일반 경로예요.")
    return out[:4]


def build_cautions(
    r: RouteCandidate, c: ScoreComponents, low_floor: LowFloorStatus, w: WeatherCondition
) -> list[str]:
    out: list[str] = []

    stair_no_elev = any(
        (s.has_stairs or s.needs_vertical_move) and s.has_elevator is not True for s in r.segments
    )
    if stair_no_elev and c.elevator < 70:
        out.append("계단 구간이 있고 승강기가 확인되지 않았어요.")

    if low_floor == "regular":
        out.append("일반버스가 포함돼 휠체어·유아차 탑승이 어려울 수 있어요.")
    elif low_floor == "unknown":
        out.append("도착 버스의 저상버스 여부가 확인되지 않았어요.")

    weather_risk = 100 - c.weather_safety
    if weather_risk >= 35:
        if w.is_heatwave:
            out.append("폭염 중 실외 보행이 길어요. 온열질환에 주의하세요.")
        elif w.is_coldwave:
            out.append("한파 중 대기시간이 길어요. 보온에 주의하세요.")
        if w.sky == "rain" or w.precipitation_mm > 0:
            out.append("비가 와 계단·경사 구간이 미끄러울 수 있어요.")
        if w.air in ("bad", "very_bad"):
            out.append("미세먼지가 나쁨 단계예요. 마스크 착용을 권장해요.")

    crosswalks = sum((s.crosswalk_count or 0) for s in r.segments)
    if crosswalks >= 4:
        out.append(f"횡단보도가 {crosswalks}곳 있어요. 횡단에 주의하세요.")

    if c.data_reliability < 70:
        out.append("일부 접근성 정보가 미확인 상태로 실제와 다를 수 있어요.")

    return out[:4]


def build_voice_summary(
    r: RouteCandidate, rank: int, low_floor: LowFloorStatus, top_caution: str | None = None
) -> str:
    lf = {
        "confirmed": "저상버스 이용 가능",
        "regular": "일반버스 포함",
        "unknown": "저상버스 여부 미확인",
        "none": "버스 미이용",
    }[low_floor]
    s = (
        f"{rank}번 경로, {r.summary}. 예상 {int(r.total_duration_min)}분, "
        f"도보 {int(r.total_walk_m)}미터, 환승 {r.transfer_count}회. {lf}."
    )
    if top_caution:
        s += f" 주의: {top_caution}"
    return s
