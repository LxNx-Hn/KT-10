import type { ProfileWeights, ScoreWeights, ScoringOptions } from '@/types';

export const SCORE_COMPONENT_KEYS: (keyof ScoreWeights)[] = [
  'accessibility',
  'walkComfort',
  'slopeComfort',
  'shadeComfort',
  'transferSimplicity',
  'elevator',
  'lowFloorBus',
  'weatherSafety',
  'safety',
  'dataReliability',
  'timeEfficiency',
];

/**
 * 프로필별 가중치 표. 각 프로필의 가중치 합은 1.0 이 되도록 설계.
 *
 * 현재 제품 계약에 따른 규칙 베이스라인:
 * - 장애인: 계단 회피/승강기/저상버스/접근성 비중 최대.
 * - 고령자: 승강기·짧은 도보(walkComfort)·날씨·적은 환승.
 * - 아동:   횡단 안전(safety)·날씨·복잡한 환승 회피.
 * - 청소년: 시간 효율·단순 환승을 중심으로 안전성을 함께 반영.
 * - 임산부: 보행·경사·승강기·환승 부담을 우선 반영.
 * - 일반:   시간 효율·보행 부담·날씨를 균형.
 */
export const PROFILE_WEIGHTS: ProfileWeights = {
  general: {
    timeEfficiency: 0.22,
    walkComfort: 0.15,
    transferSimplicity: 0.1,
    weatherSafety: 0.1,
    safety: 0.09,
    slopeComfort: 0.08,
    shadeComfort: 0.06,
    accessibility: 0.06,
    dataReliability: 0.06,
    elevator: 0.04,
    lowFloorBus: 0.04,
  },
  elderly: {
    walkComfort: 0.17,
    slopeComfort: 0.14,
    elevator: 0.14,
    accessibility: 0.11,
    transferSimplicity: 0.1,
    weatherSafety: 0.1,
    shadeComfort: 0.07,
    lowFloorBus: 0.06,
    timeEfficiency: 0.04,
    safety: 0.04,
    dataReliability: 0.03,
  },
  child: {
    safety: 0.24,
    transferSimplicity: 0.14,
    walkComfort: 0.12,
    weatherSafety: 0.1,
    timeEfficiency: 0.08,
    shadeComfort: 0.07,
    dataReliability: 0.07,
    slopeComfort: 0.05,
    accessibility: 0.05,
    elevator: 0.05,
    lowFloorBus: 0.03,
  },
  youth: {
    timeEfficiency: 0.24,
    transferSimplicity: 0.15,
    safety: 0.12,
    walkComfort: 0.12,
    dataReliability: 0.09,
    weatherSafety: 0.08,
    shadeComfort: 0.05,
    slopeComfort: 0.04,
    accessibility: 0.04,
    elevator: 0.04,
    lowFloorBus: 0.03,
  },
  disabled: {
    accessibility: 0.16,
    elevator: 0.16,
    lowFloorBus: 0.16,
    walkComfort: 0.13,
    slopeComfort: 0.11,
    transferSimplicity: 0.08,
    weatherSafety: 0.06,
    dataReliability: 0.05,
    shadeComfort: 0.04,
    safety: 0.04,
    timeEfficiency: 0.01,
  },
  pregnant: {
    walkComfort: 0.18,
    slopeComfort: 0.15,
    elevator: 0.14,
    transferSimplicity: 0.11,
    weatherSafety: 0.1,
    shadeComfort: 0.08,
    accessibility: 0.08,
    safety: 0.05,
    timeEfficiency: 0.04,
    dataReliability: 0.04,
    lowFloorBus: 0.03,
  },
};

/**
 * 이번 이동 조건이 켜졌을 때 관련 가중치를 동적으로 보정한다.
 * 보정 후에도 합이 1이 되도록 정규화한다.
 */
export function applyOptionWeights(
  base: ScoreWeights,
  opts: ScoringOptions,
): ScoreWeights {
  const w: ScoreWeights = { ...base };
  if (opts.carryLuggage) {
    w.walkComfort += 0.15;
    w.transferSimplicity += 0.08;
    w.accessibility += 0.05;
  }
  if (opts.stroller) {
    w.accessibility += 0.12;
    w.elevator += 0.1;
    w.walkComfort += 0.08;
    w.lowFloorBus += 0.05;
  }
  if (opts.lowFloorPriority) {
    w.lowFloorBus += 0.15;
    w.elevator += 0.05;
  }
  if (opts.weatherAvoid) {
    w.weatherSafety += 0.15;
  }
  if (opts.avoidStairs) {
    // 계단 회피·승강기 우선: 승강기/접근성 비중 강화
    w.elevator += 0.12;
    w.accessibility += 0.08;
  }
  if (opts.shadePriority) {
    w.shadeComfort += 0.2;
  }
  if (opts.minimizeTransfers) {
    w.transferSimplicity += 0.2;
  }
  return normalizeWeights(w);
}

/** 가중치 합을 1.0 으로 정규화 */
export function normalizeWeights(w: ScoreWeights): ScoreWeights {
  const sum = SCORE_COMPONENT_KEYS.reduce((acc, key) => acc + w[key], 0);
  if (sum === 0) return w;
  const out = {} as ScoreWeights;
  for (const key of SCORE_COMPONENT_KEYS) out[key] = w[key] / sum;
  return out;
}
