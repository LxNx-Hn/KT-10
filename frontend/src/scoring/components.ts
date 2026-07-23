/**
 * 하위 점수 계산 함수 모음 (기획서 §7).
 * 모든 함수는 순수 함수이며 "좋음 점수(0~100, 높을수록 이상적)"를 반환한다.
 * 프로필 가중치는 여기서 적용하지 않는다(가중치는 weights.ts + engine.ts 담당).
 */
import type { RouteCandidate, RouteSegment, WeatherCondition } from '@/types';
import { avg, clamp } from './utils';

const walkSegs = (r: RouteCandidate) => r.segments.filter((s) => s.mode === 'walk');
const busSegs = (r: RouteCandidate) => r.segments.filter((s) => s.mode === 'bus');
const verticalSegs = (r: RouteCandidate) =>
  r.segments.filter((s) => s.needsVerticalMove);

/** 계단 수 추정: 명시값 우선, hasStairs만 있으면 기본 20단 가정 */
function stairCount(s: RouteSegment): number {
  if (s.stairsCount != null) return s.stairsCount;
  return s.hasStairs ? 20 : 0;
}

/* ① 접근성 점수 — 단차 없는 연속 이동 가능성 */
export function scoreAccessibility(r: RouteCandidate): number {
  let penalty = 0;
  for (const s of r.segments) {
    const stairs = stairCount(s);
    if (stairs > 0) {
      // 승강기로 완화되면 감점 축소, 미확인/없음이면 큰 감점
      if (s.hasElevator === true) penalty += 3;
      else if (s.hasElevator === false) penalty += 18;
      else penalty += 11; // 미확인
    }
    if (s.hasSlope) penalty += 8;
    if (s.mode === 'bus') {
      if (s.isLowFloorBus === false) penalty += 8;
      else if (s.isLowFloorBus === undefined) penalty += 4;
    }
  }
  return clamp(100 - penalty);
}

/* ② 보행 부담 점수 — 거리·시간·계단·경사·환승 누적 부담(좋음 점수로 반환) */
export function scoreWalkComfort(r: RouteCandidate): number {
  const distPenalty = clamp(r.totalWalkM / 25, 0, 50); // 1250m≈50
  const walkMin = walkSegs(r).reduce((a, s) => a + s.durationMin, 0);
  const timePenalty = clamp(walkMin * 0.8, 0, 20);
  const stairs = r.segments.reduce((a, s) => a + stairCount(s), 0);
  const stairPenalty = clamp(stairs * 0.6, 0, 25);
  const slopePenalty = clamp(
    r.segments.filter((s) => s.hasSlope).length * 6,
    0,
    18,
  );
  const transferPenalty = clamp(r.transferCount * 4, 0, 16);
  return clamp(
    100 - distPenalty - timePenalty - stairPenalty - slopePenalty - transferPenalty,
  );
}

/* ③ 승강기 이용 가능성 점수 — 수직이동 구간의 승강기 확보 정도 */
export function scoreElevator(r: RouteCandidate): number {
  const vs = verticalSegs(r);
  if (vs.length === 0) return 85; // 수직이동 없음 = 장벽 없음
  const perSeg = vs.map((s) => {
    if (s.hasElevator === true) return 100;
    if (s.hasElevator === false) return 25; // 계단만 존재
    return 50; // 미확인
  });
  return clamp(avg(perSeg, 85));
}

/* ④ 저상버스 이용 가능성 점수 */
export function scoreLowFloorBus(r: RouteCandidate): number {
  const bs = busSegs(r);
  if (bs.length === 0) return 80; // 버스 미이용 = 중립(불리하지 않음)
  const perSeg = bs.map((s) => {
    if (s.isLowFloorBus === true) return 100;
    if (s.isLowFloorBus === false) return 35; // 일반버스 확정
    return 55; // 미확인
  });
  // 보수적: 평균과 최악값을 절반씩 반영
  const mean = avg(perSeg, 80);
  const worst = Math.min(...perSeg);
  return clamp(mean * 0.5 + worst * 0.5);
}

/* ⑤ 날씨 위험 점수 — 날씨 × 노출(실외 보행/대기/계단) (좋음 점수로 반환) */
export function scoreWeatherSafety(
  r: RouteCandidate,
  w: WeatherCondition,
): number {
  const outdoorWalk = walkSegs(r).filter((s) => s.outdoor);
  const outdoorWalkMin = outdoorWalk.reduce((a, s) => a + s.durationMin, 0);
  // 검증된 그늘만 노출시간을 감면한다. 미확인 그늘을 0으로 대입하지 않는다.
  let heatExposedWalkMin = outdoorWalkMin;
  if (
    (r.shade?.status === 'estimated_demo' || r.shade?.status === 'estimated_public')
    && r.shade.shadeRatio !== undefined
  ) {
    heatExposedWalkMin *= 1 - r.shade.shadeRatio;
  }
  const waitMin = busSegs(r).reduce((a, s) => a + (s.waitMin ?? 0), 0);
  const hasStairsOrSlope = r.segments.some((s) => s.hasStairs || s.hasSlope);

  let risk = 0;
  // 폭염 + 긴 실외 보행
  if (w.isHeatwave || w.feelsLikeC >= 33) {
    risk += clamp(heatExposedWalkMin * 1.5, 0, 35) + (w.isHeatwave ? 10 : 0);
  }
  // 한파 + 긴 대기시간
  if (w.isColdwave || w.feelsLikeC <= -5) {
    risk += clamp(waitMin * 2, 0, 25) + clamp(outdoorWalkMin * 0.5, 0, 10);
  }
  // 비/눈 + 계단·경사(미끄럼)
  if (w.precipitationMm > 0 || w.sky === 'rain' || w.sky === 'snow') {
    risk += 10 + (hasStairsOrSlope ? 15 : 0) + clamp(outdoorWalkMin * 0.5, 0, 10);
  }
  // 미세먼지 나쁨 + 긴 실외 이동
  if (w.air === 'bad') risk += clamp(outdoorWalkMin * 1.0, 0, 20);
  if (w.air === 'very_bad') risk += clamp(outdoorWalkMin * 1.0, 0, 20) + 10;
  // 강풍
  if (w.windMs >= 9) risk += 8;

  return clamp(100 - risk);
}

/* ⑥ 안전성 점수 — 횡단보도·환승 복잡도 (사고정보는 서비스 범위에서 제외) */
export function scoreSafety(r: RouteCandidate): number {
  const crosswalks = r.segments.reduce((a, s) => a + (s.crosswalkCount ?? 0), 0);
  let penalty = clamp(crosswalks * 5, 0, 30);
  penalty += clamp(r.transferCount * 2, 0, 10);
  return clamp(100 - penalty);
}

/* ⑦ 데이터 신뢰도 점수 — 확인 가능한 정보 중 실제 확인된 비율 */
export function scoreDataReliability(r: RouteCandidate): number {
  let known = 0;
  let total = 0;
  for (const s of r.segments) {
    if (s.mode === 'bus') {
      total += 1;
      if (s.isLowFloorBus !== undefined) known += 1;
    }
    if (s.needsVerticalMove) {
      total += 1;
      if (s.hasElevator !== undefined) known += 1;
    }
  }
  if (total === 0) return 90; // 불확실 요소 없음
  return clamp(40 + (known / total) * 60); // 40~100
}

/* ⑧ 시간 효율 점수 — 후보군 중 최단 대비 (engine 에서 fastestMin 주입) */
export function scoreTimeEfficiency(durationMin: number, fastestMin: number): number {
  const extra = Math.max(0, durationMin - fastestMin);
  return clamp(100 - extra * 2.5, 40, 100); // +24분 → 40점
}
