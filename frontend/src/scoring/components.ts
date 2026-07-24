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
function stairCount(s: RouteSegment): number | undefined {
  if (s.stairsCount != null) return s.stairsCount;
  if (s.hasStairs === true) return 20;
  if (s.hasStairs === false) return 0;
  return undefined;
}

/* ① 접근성 점수 — 단차 없는 연속 이동 가능성 */
export function scoreAccessibility(r: RouteCandidate): number | undefined {
  const relevant = r.segments.filter(
    (segment) => segment.mode === 'walk'
      || segment.mode === 'transfer'
      || segment.needsVerticalMove,
  );
  if (relevant.length === 0) return undefined;
  let penalty = 0;
  for (const s of relevant) {
    const stairs = s.mode === 'walk' || s.mode === 'transfer'
      ? stairCount(s)
      : 0;
    if (stairs === undefined) return undefined;
    if (stairs > 0) {
      if (s.hasElevator === true) penalty += 3;
      else if (s.hasElevator === false) penalty += 18;
      else return undefined;
    }
    if (stairs === 0 && s.needsVerticalMove) {
      if (s.hasElevator === undefined) return undefined;
      if (s.hasElevator === false) penalty += 18;
    }
  }
  return clamp(100 - penalty);
}

/* ② 보행 부담 점수 — 거리·시간·계단·경사·환승 누적 부담(좋음 점수로 반환) */
export function scoreWalkComfort(r: RouteCandidate): number {
  const distPenalty = clamp(r.totalWalkM / 25, 0, 50); // 1250m≈50
  const walkMin = walkSegs(r).reduce((a, s) => a + s.durationMin, 0);
  const timePenalty = clamp(walkMin * 0.8, 0, 20);
  const transferPenalty = clamp(r.transferCount * 4, 0, 16);
  return clamp(
    100 - distPenalty - timePenalty - transferPenalty,
  );
}

/** 90m 지형 추정이 있을 때만 경사 편의 점수를 계산한다. */
export function scoreSlopeComfort(r: RouteCandidate): number | undefined {
  const terrain = r.terrain;
  if (
    terrain?.status !== 'estimated_90m'
    || terrain.maxSlopePercent === undefined
    || terrain.minSlopePercent === undefined
  ) {
    return undefined;
  }
  const worstGrade = Math.max(
    Math.abs(terrain.maxSlopePercent),
    Math.abs(terrain.minSlopePercent),
  );
  return clamp(100 - worstGrade * 8);
}

/** 확인 가능한 주간 건물 그늘만 점수화하고 미확인은 undefined로 둔다. */
export function scoreShadeComfort(r: RouteCandidate): number | undefined {
  const shade = r.shade;
  if (
    !shade
    || (shade.status !== 'estimated_demo' && shade.status !== 'estimated_public')
    || shade.shadeRatio === undefined
  ) {
    return undefined;
  }
  return clamp(shade.shadeRatio * 100);
}

/** 환승이 없으면 100점, 1회마다 25점씩 감소한다. */
export function scoreTransferSimplicity(r: RouteCandidate): number {
  return clamp(100 - r.transferCount * 25);
}

/* ⑥ 승강기 이용 가능성 점수 — 수직이동 구간의 승강기 확보 정도 */
export function scoreElevator(r: RouteCandidate): number | undefined {
  const vs = verticalSegs(r);
  if (vs.length === 0) return undefined;
  if (vs.some((segment) => segment.hasElevator === undefined)) return undefined;
  const perSeg = vs.map((s) => {
    if (s.hasElevator === true) return 100;
    return 25;
  });
  return clamp(avg(perSeg, 0));
}

/* ⑦ 저상버스 이용 가능성 점수 */
export function scoreLowFloorBus(r: RouteCandidate): number | undefined {
  const bs = busSegs(r);
  if (bs.length === 0) return undefined;
  if (bs.some((segment) => segment.isLowFloorBus === undefined)) return undefined;
  const perSeg = bs.map((s) => {
    if (s.isLowFloorBus === true) return 100;
    return 35;
  });
  // 보수적: 평균과 최악값을 절반씩 반영
  const mean = avg(perSeg, 0);
  const worst = Math.min(...perSeg);
  return clamp(mean * 0.5 + worst * 0.5);
}

/* ⑧ 날씨 위험 점수 — 날씨 × 노출(실외 보행/대기/계단) (좋음 점수로 반환) */
export function scoreWeatherSafety(
  r: RouteCandidate,
  w: WeatherCondition,
): number | undefined {
  const walks = walkSegs(r);
  if (walks.length === 0 || walks.some((segment) => segment.outdoor === undefined)) {
    // 미확인 노출을 실외 0분으로 간주해 날씨안전 100점을 만들지 않는다.
    return undefined;
  }
  const outdoorWalk = walks.filter((s) => s.outdoor);
  const outdoorWalkMin = outdoorWalk.reduce((a, s) => a + s.durationMin, 0);
  // 검증된 그늘만 노출시간을 감면한다. 미확인 그늘을 0으로 대입하지 않는다.
  let heatExposedWalkMin = outdoorWalkMin;
  if (
    (r.shade?.status === 'estimated_demo' || r.shade?.status === 'estimated_public')
    && r.shade.shadeRatio !== undefined
  ) {
    heatExposedWalkMin *= 1 - r.shade.shadeRatio;
  }
  const buses = busSegs(r);
  if (
    (w.isColdwave || w.feelsLikeC <= -5)
    && buses.some((segment) => segment.waitMin === undefined)
  ) return undefined;
  const waitMin = buses.reduce((a, s) => a + (s.waitMin ?? 0), 0);
  if (
    (w.precipitationMm > 0 || w.sky === 'rain' || w.sky === 'snow')
    && r.segments.some(
      (segment) => (
        segment.mode === 'walk' || segment.mode === 'transfer'
      ) && segment.hasStairs === undefined && segment.stairsCount === undefined,
    )
  ) return undefined;
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

/* ⑨ 안전성 점수 — 횡단보도·환승 복잡도 (사고정보는 서비스 범위에서 제외) */
export function scoreSafety(r: RouteCandidate): number | undefined {
  const walks = walkSegs(r);
  if (walks.length === 0 || walks.some((segment) => segment.crosswalkCount === undefined)) {
    return undefined;
  }
  const crosswalks = walks.reduce((a, s) => a + s.crosswalkCount!, 0);
  let penalty = clamp(crosswalks * 5, 0, 30);
  penalty += clamp(r.transferCount * 2, 0, 10);
  return clamp(100 - penalty);
}

/* ⑩ 데이터 신뢰도 점수 — 확인 가능한 정보 중 실제 확인된 비율 */
export function scoreDataReliability(r: RouteCandidate): number {
  let known = 0;
  let total = 0;
  for (const s of r.segments) {
    if (s.mode === 'walk' || s.mode === 'transfer') {
      total += 1;
      if (s.stairsCount !== undefined || s.hasStairs !== undefined) known += 1;
    }
    if (s.mode === 'walk') {
      total += 1;
      if (s.crosswalkCount !== undefined) known += 1;
    }
    if (s.mode === 'bus') {
      total += 1;
      if (s.isLowFloorBus !== undefined) known += 1;
    }
    if (s.needsVerticalMove) {
      total += 1;
      if (s.hasElevator !== undefined) known += 1;
    }
  }
  if (total === 0) return 100;
  return clamp(40 + (known / total) * 60); // 40~100
}

/* ⑪ 시간 효율 점수 — 후보군 중 최단 대비 (engine 에서 fastestMin 주입) */
export function scoreTimeEfficiency(durationMin: number, fastestMin: number): number {
  const extra = Math.max(0, durationMin - fastestMin);
  return clamp(100 - extra * 2.5, 40, 100); // +24분 → 40점
}
