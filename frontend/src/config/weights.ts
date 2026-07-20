import type { ProfileWeights, ScoreComponents } from '@/types';

/**
 * 프로필별 가중치 표. 각 프로필의 가중치 합은 1.0 이 되도록 설계.
 *
 * 설계 근거(기획서 4·7장):
 * - 장애인: 계단 회피/승강기/저상버스/접근성 비중 최대.
 * - 고령자: 승강기·짧은 도보(walkComfort)·날씨·적은 환승.
 * - 아동:   횡단 안전(safety)·날씨·복잡한 환승 회피.
 * - 일반:   시간 효율·보행 부담·날씨를 균형.
 */
export const PROFILE_WEIGHTS: ProfileWeights = {
  general: {
    timeEfficiency: 0.22,
    walkComfort: 0.18,
    weatherSafety: 0.15,
    safety: 0.12,
    accessibility: 0.1,
    dataReliability: 0.1,
    elevator: 0.08,
    lowFloorBus: 0.05,
  },
  elderly: {
    walkComfort: 0.22,
    elevator: 0.2,
    weatherSafety: 0.18,
    accessibility: 0.12,
    timeEfficiency: 0.08,
    lowFloorBus: 0.08,
    safety: 0.07,
    dataReliability: 0.05,
  },
  child: {
    safety: 0.28,
    walkComfort: 0.16,
    weatherSafety: 0.16,
    timeEfficiency: 0.1,
    accessibility: 0.08,
    elevator: 0.08,
    dataReliability: 0.1,
    lowFloorBus: 0.04,
  },
  disabled: {
    accessibility: 0.2,
    elevator: 0.2,
    lowFloorBus: 0.2,
    walkComfort: 0.15,
    weatherSafety: 0.08,
    safety: 0.07,
    dataReliability: 0.07,
    timeEfficiency: 0.03,
  },
};

/**
 * 조건 모드(저상버스 우선/날씨 회피)가 켜졌을 때 가중치를 동적으로 보정한다.
 * 보정 후에도 합이 1이 되도록 정규화한다.
 */
export function applyOptionWeights(
  base: ScoreComponents,
  opts: { carryLuggage?: boolean; lowFloorPriority?: boolean; weatherAvoid?: boolean; avoidStairs?: boolean },
): ScoreComponents {
  const w: ScoreComponents = { ...base };
  if (opts.carryLuggage) {
    w.walkComfort += 0.15;
    w.accessibility += 0.05;
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
  return normalizeWeights(w);
}

/** 가중치 합을 1.0 으로 정규화 */
export function normalizeWeights(w: ScoreComponents): ScoreComponents {
  const keys = Object.keys(w) as (keyof ScoreComponents)[];
  const sum = keys.reduce((acc, k) => acc + w[k], 0);
  if (sum === 0) return w;
  const out = {} as ScoreComponents;
  for (const k of keys) out[k] = w[k] / sum;
  return out;
}
