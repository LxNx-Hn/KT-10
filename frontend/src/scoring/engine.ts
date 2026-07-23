/**
 * 점수화 엔진 오케스트레이터.
 * 경로 후보 + 날씨 + 프로필 + 옵션 → 채점·정렬된 추천 경로.
 *
 * 흐름(기획서 §6):
 *  1) 후보별 11개 하위 점수 계산(경사·그늘 미확인은 제외)
 *  2) 프로필 가중치(+옵션 보정) 적용 → 최종 점수
 *  3) 정렬 후 상위 3개 + 이유/주의/음성요약
 */
import type {
  ProfileId,
  RouteCandidate,
  RouteScore,
  ScoreComponents,
  ScoreWeights,
  ScoredRoute,
  ScoringOptions,
  WeatherCondition,
} from '@/types';
import {
  PROFILE_WEIGHTS,
  SCORE_COMPONENT_KEYS,
  applyOptionWeights,
} from '@/config/weights';
import {
  scoreAccessibility,
  scoreDataReliability,
  scoreElevator,
  scoreLowFloorBus,
  scoreSafety,
  scoreShadeComfort,
  scoreSlopeComfort,
  scoreTimeEfficiency,
  scoreTransferSimplicity,
  scoreWalkComfort,
  scoreWeatherSafety,
} from './components';
import {
  buildCautions,
  buildReasons,
  buildVoiceSummary,
  deriveLowFloorStatus,
} from './explain';
import { clamp, round1 } from './utils';

/** 가중합으로 최종 점수 계산 */
export function weightedFinal(
  c: ScoreComponents,
  w: ScoreWeights,
): number {
  const available = SCORE_COMPONENT_KEYS.filter((key) => c[key] !== undefined);
  const availableWeight = available.reduce((sum, key) => sum + w[key], 0);
  if (availableWeight <= 0) {
    throw new Error('점수화할 수 있는 확인된 경로 특성이 없습니다.');
  }
  const sum = available.reduce((acc, key) => acc + c[key]! * w[key], 0);
  return clamp(sum / availableWeight);
}

/** 단일 경로 채점(시간효율은 후보군 최단값 fastestMin 주입 필요) */
export function scoreRoute(
  route: RouteCandidate,
  weather: WeatherCondition,
  profile: ProfileId,
  fastestMin: number,
  rank: number,
  opts: ScoringOptions = {},
): RouteScore {
  const components: ScoreComponents = {
    accessibility: scoreAccessibility(route),
    walkComfort: scoreWalkComfort(route),
    slopeComfort: scoreSlopeComfort(route),
    shadeComfort: scoreShadeComfort(route),
    transferSimplicity: scoreTransferSimplicity(route),
    elevator: scoreElevator(route),
    lowFloorBus: scoreLowFloorBus(route),
    weatherSafety: scoreWeatherSafety(route, weather),
    safety: scoreSafety(route),
    dataReliability: scoreDataReliability(route),
    timeEfficiency: scoreTimeEfficiency(route.totalDurationMin, fastestMin),
  };

  const weights = applyOptionWeights(PROFILE_WEIGHTS[profile], opts);
  const finalScore = round1(weightedFinal(components, weights));

  const lowFloorStatus = deriveLowFloorStatus(route);
  const reasons = buildReasons(route, components, lowFloorStatus);
  const cautions = buildCautions(route, components, lowFloorStatus, weather);
  const voiceSummary = buildVoiceSummary(route, rank, lowFloorStatus, cautions[0]);

  return {
    routeId: route.id,
    components: roundComponents(components),
    display: {
      walkBurden: components.walkComfort === undefined
        ? undefined
        : round1(100 - components.walkComfort),
      weatherRisk: components.weatherSafety === undefined
        ? undefined
        : round1(100 - components.weatherSafety),
    },
    finalScore,
    scoreKind: 'rule_baseline',
    lowFloorStatus,
    reasons,
    cautions,
    voiceSummary,
  };
}

/**
 * 후보군 전체 채점·정렬 → 상위 N개(기본 3개) 반환.
 * 저상버스 우선 옵션이 켜지면 동점 시 저상버스 확정 경로를 우선한다.
 */
export function recommendRoutes(
  candidates: RouteCandidate[],
  weather: WeatherCondition,
  profile: ProfileId,
  opts: ScoringOptions = {},
  topN = 3,
): ScoredRoute[] {
  if (candidates.length === 0) return [];
  const fastestMin = Math.min(...candidates.map((c) => c.totalDurationMin));

  const scored: ScoredRoute[] = candidates.map((route, i) => ({
    route,
    score: scoreRoute(route, weather, profile, fastestMin, i + 1, opts),
  }));

  scored.sort((a, b) => {
    const diff = b.score.finalScore - a.score.finalScore;
    if (Math.abs(diff) > 0.05) return diff;
    // 동점 처리: 저상버스 우선 옵션 시 확정 저상버스 우대
    if (opts.lowFloorPriority) {
      const rank = (s: ScoredRoute) =>
        s.score.lowFloorStatus === 'confirmed' ? 1 : 0;
      const r = rank(b) - rank(a);
      if (r !== 0) return r;
    }
    return a.route.totalDurationMin - b.route.totalDurationMin;
  });

  // 정렬 후 순위 기준으로 음성 요약의 번호를 재부여
  return scored.slice(0, topN).map((sr, idx) => ({
    route: sr.route,
    score: {
      ...sr.score,
      voiceSummary: buildVoiceSummary(
        sr.route,
        idx + 1,
        sr.score.lowFloorStatus,
        sr.score.cautions[0],
      ),
    },
  }));
}

function roundComponents(c: ScoreComponents): ScoreComponents {
  const out = {} as Record<keyof ScoreComponents, number | undefined>;
  SCORE_COMPONENT_KEYS.forEach((key) => {
    const value = c[key];
    out[key] = value === undefined ? undefined : round1(value);
  });
  return out as ScoreComponents;
}
