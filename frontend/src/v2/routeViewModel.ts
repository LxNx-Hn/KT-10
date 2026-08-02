import { PROFILES } from '@/config/profiles';
import type {
  ProfileId,
  RouteCandidate,
  RouteScore,
  ScoredRoute,
} from '@/types';
import {
  formatSlopePercent,
  resolvePeakSlopePercent,
  resolveSlopeLevel,
  SLOPE_LEVEL_LABELS,
  type SlopeLevelId,
} from './utils/slopeLevel';

/**
 * live AI: relative_fit_score(후보 내 min–max) × 100.
 * rule_baseline: 프로필·옵션 가중 하위지표 가중합(0~100).
 * 둘 다 절대 안전 점수가 아니며, 화면에는 맞춤 적합도로 통일한다.
 */
export const SCORE_KIND_LABEL: Record<
  NonNullable<RouteScore['scoreKind']>,
  string
> = {
  rule_baseline: '맞춤 적합도',
  bootstrap_baseline: '맞춤 적합도',
  human_model: '맞춤 적합도',
};

/** 복수 후보 결과 목록용 점수 의미 설명 */
export const ROUTE_SCORE_DISCLAIMER =
  '선택한 프로필·상황·옵션을 기준으로 후보 경로를 비교한 점수예요.';

/** 단일 후보일 때 — 비교를 전제하지 않는다. */
export const ROUTE_SCORE_DISCLAIMER_SINGLE =
  '선택한 프로필·상황·옵션을 기준으로 산정한 점수예요.';

export const SCORE_COMPARISON_HINT =
  '선택한 조건을 기준으로 후보 경로를 비교한 점수';

export const SCORE_SINGLE_HINT =
  '선택한 조건을 기준으로 산정한 점수';

export const SCORE_UNAVAILABLE_LABEL = '적합도 산정 불가';

export function routeScoreDisclaimer(routeCount: number): string {
  return routeCount > 1 ? ROUTE_SCORE_DISCLAIMER : ROUTE_SCORE_DISCLAIMER_SINGLE;
}

export type V2ScoreDisplay = {
  available: boolean;
  value: number | null;
  rounded: number | null;
  kind: NonNullable<RouteScore['scoreKind']>;
  /** 예: "맞춤 적합도 100점" / "적합도 산정 불가" */
  summaryLabel: string;
  ariaLabel: string;
};

/** finalScore가 유한 숫자일 때만 점수로 표시. null/NaN을 0으로 오인하지 않는다. */
export function resolveScoreDisplay(
  finalScore: unknown,
  scoreKind: NonNullable<RouteScore['scoreKind']> = 'rule_baseline',
  options: { canCompare?: boolean } = {},
): V2ScoreDisplay {
  const label = SCORE_KIND_LABEL[scoreKind];
  const hint = options.canCompare === false
    ? SCORE_SINGLE_HINT
    : SCORE_COMPARISON_HINT;
  if (typeof finalScore !== 'number' || !Number.isFinite(finalScore)) {
    return {
      available: false,
      value: null,
      rounded: null,
      kind: scoreKind,
      summaryLabel: SCORE_UNAVAILABLE_LABEL,
      ariaLabel: SCORE_UNAVAILABLE_LABEL,
    };
  }
  const rounded = Math.round(finalScore);
  return {
    available: true,
    value: finalScore,
    rounded,
    kind: scoreKind,
    summaryLabel: `${label} ${rounded}점`,
    ariaLabel: `${label} ${rounded}점, ${hint}`,
  };
}

/**
 * 백엔드 assign_characteristics / AI route_traits 의 lowest_slope 비교 기준:
 * max(|max_slope_percent|, |min_slope_percent|) — 구간 최대(가장 급한) 경사.
 */
export const LOWEST_SLOPE_RELATIVE_LABEL =
  '후보 중 구간 최대 경사가 가장 낮은 길';

/** 절대 완만 표현. 평균 경사 ≤2% 이고 상대 비교 배지가 없을 때만 노출. */
export const GENTLE_SLOPE_ABSOLUTE_LABEL = '경사가 완만한 길';

const CHARACTERISTIC_LABEL: Record<
  NonNullable<RouteCandidate['characteristics']>[number],
  string
> = {
  fastest: '제일 빠른 길',
  shortest_walk: '도보가 가장 짧은 길',
  lowest_slope: LOWEST_SLOPE_RELATIVE_LABEL,
  most_shade: '건물 그늘이 가장 많은 길',
  fewest_transfers: '환승이 가장 적은 길',
  stair_free: '계단 없음',
  low_floor_confirmed: '저상버스 이용 가능',
};

const ABSOLUTE_GENTLE_PHRASES = new Set([
  GENTLE_SLOPE_ABSOLUTE_LABEL,
  '경사가 가장 완만한 길',
]);

/** 후보 간 상대 비교로만 성립하는 characteristic */
const RELATIVE_CHARACTERISTICS = new Set<
  NonNullable<RouteCandidate['characteristics']>[number]
>([
  'fastest',
  'shortest_walk',
  'lowest_slope',
  'most_shade',
  'fewest_transfers',
]);

/** 후보 간 상대 비교 trait labelId */
const RELATIVE_TRAIT_IDS = new Set([
  'fastest',
  'shortest',
  'fewest_transfers',
  'lowest_slope',
  'most_shade',
  'most_dongbaekjeon_stores',
]);

function hasRelativeLowestSlope(route: RouteCandidate): boolean {
  if ((route.characteristics ?? []).includes('lowest_slope')) return true;
  return (route.traitLabels ?? []).some(
    (trait) =>
      trait.evidenceStatus !== 'unavailable'
      && trait.labelId === 'lowest_slope',
  );
}

function canShowAbsoluteGentleSlope(route: RouteCandidate): boolean {
  const avg = route.terrain?.avgSlopePercent;
  if (
    route.terrain?.status !== 'estimated_90m'
    || typeof avg !== 'number'
    || !Number.isFinite(avg)
  ) {
    return false;
  }
  return Math.abs(avg) <= 2;
}

function looksRelativeComparisonLabel(label: string): boolean {
  return (
    label.includes('후보 중')
    || label.includes('다른 경로보다')
    || label.includes('가장 빠른')
    || label.includes('가장 짧은')
    || label.includes('가장 적은')
    || label.includes('가장 많은')
    || label.includes('가장 완만')
    || label.includes('가장 추천')
    || label.startsWith('제일 빠른')
    || label === LOWEST_SLOPE_RELATIVE_LABEL
  );
}

/**
 * 특성 배지: 복수 후보에서만 상대 비교 배지.
 * 단일 후보에서는 상대 배지를 숨기고, 평균 ≤2%일 때만 절대 완만 허용.
 * 수치 배지(terrain facts)는 여기서 다루지 않는다.
 */
function resolveTraitAndCharacteristicLabels(
  route: RouteCandidate,
  canCompare: boolean,
): {
  characteristicLabels: string[];
  traitLabels: string[];
} {
  const relativeSlope = canCompare && hasRelativeLowestSlope(route);
  const absoluteOk = !relativeSlope && canShowAbsoluteGentleSlope(route);

  const characteristicLabels = unique(
    (route.characteristics ?? [])
      .filter(
        (characteristic) =>
          canCompare || !RELATIVE_CHARACTERISTICS.has(characteristic),
      )
      .map((characteristic) => {
        if (characteristic === 'lowest_slope') return LOWEST_SLOPE_RELATIVE_LABEL;
        return CHARACTERISTIC_LABEL[characteristic];
      }),
  );

  const traitLabels: string[] = [];
  for (const trait of route.traitLabels ?? []) {
    if (trait.evidenceStatus === 'unavailable') continue;

    if (trait.labelId === 'lowest_slope') {
      if (
        canCompare
        && !characteristicLabels.includes(LOWEST_SLOPE_RELATIVE_LABEL)
      ) {
        traitLabels.push(LOWEST_SLOPE_RELATIVE_LABEL);
      }
      continue;
    }

    const looksAbsoluteGentle =
      trait.labelId === 'gentle_slope'
      || ABSOLUTE_GENTLE_PHRASES.has(trait.displayLabel);

    if (looksAbsoluteGentle) {
      if (absoluteOk) traitLabels.push(GENTLE_SLOPE_ABSOLUTE_LABEL);
      continue;
    }

    if (!canCompare && RELATIVE_TRAIT_IDS.has(trait.labelId)) continue;
    if (!canCompare && looksRelativeComparisonLabel(trait.displayLabel)) {
      continue;
    }

    traitLabels.push(trait.displayLabel);
  }

  if (
    absoluteOk
    && !characteristicLabels.includes(LOWEST_SLOPE_RELATIVE_LABEL)
    && !traitLabels.includes(GENTLE_SLOPE_ABSOLUTE_LABEL)
  ) {
    traitLabels.push(GENTLE_SLOPE_ABSOLUTE_LABEL);
  }

  return {
    characteristicLabels,
    traitLabels: unique(traitLabels),
  };
}

export type V2RouteFactKind =
  | 'advantage'
  | 'caution'
  | 'estimate'
  | 'neutral'
  | 'unknown';

export interface V2RouteFact {
  id: string;
  label: string;
  kind: V2RouteFactKind;
  detail?: string;
  /** 경사 배지 전용 등급. 있을 때만 등급 색상 클래스를 쓴다. */
  slopeLevel?: SlopeLevelId;
  /** 접근성용 전체 설명 (등급 포함). */
  title?: string;
}

export interface V2RouteViewModel {
  routeId: string;
  rank: number;
  profile: ProfileId;
  profileLabel: string;
  title: string;
  summary: string;
  meta: string;
  stats: {
    durationMin: number;
    walkM: number;
    transferCount: number;
  };
  score: V2ScoreDisplay;
  scoreKindLabel: string;
  characteristicLabels: string[];
  traitLabels: string[];
  facts: V2RouteFact[];
  needsConfirmation: string[];
  reasons: string[];
  cautions: string[];
  voiceSummary: string;
}

function unique(values: string[]): string[] {
  return Array.from(new Set(values));
}

function stairFact(route: RouteCandidate): V2RouteFact | null {
  const walkSegments = route.segments.filter(
    (segment) => segment.mode === 'walk' || segment.mode === 'transfer',
  );
  const hasStairs = walkSegments.some(
    (segment) =>
      segment.hasStairs === true || (segment.stairsCount ?? 0) > 0,
  );
  const stairsCount = walkSegments.reduce(
    (sum, segment) => sum + (segment.stairsCount ?? 0),
    0,
  );
  const stairFreeConfirmed =
    walkSegments.length > 0 &&
    walkSegments.every(
      (segment) =>
        segment.hasStairs === false || segment.stairsCount === 0,
    );

  if (hasStairs) {
    return {
      id: 'stairs',
      label: stairsCount > 0 ? `계단 ${stairsCount}개` : '계단 포함',
      kind: 'caution',
    };
  }
  if (stairFreeConfirmed) {
    return { id: 'stairs', label: '계단 없음', kind: 'advantage' };
  }
  return null;
}

function elevatorFact(route: RouteCandidate): V2RouteFact | null {
  const verticalSegments = route.segments.filter(
    (segment) => segment.needsVerticalMove === true,
  );
  const noVerticalMoveConfirmed =
    route.segments.length > 0 &&
    route.segments.every((segment) => segment.needsVerticalMove === false);
  const hasElevator = verticalSegments.some(
    (segment) => segment.hasElevator === true,
  );
  const elevatorUnavailable =
    verticalSegments.length > 0 &&
    verticalSegments.every((segment) => segment.hasElevator === false);
  const stationElevatorSegments = route.segments.filter(
    (segment) => segment.mode === 'subway' && segment.hasElevator !== undefined,
  );

  if (noVerticalMoveConfirmed) {
    return {
      id: 'elevator',
      label: '수직이동 없음',
      kind: 'neutral',
    };
  }
  if (verticalSegments.length === 0) {
    if (
      stationElevatorSegments.length > 0
      && stationElevatorSegments.every((segment) => segment.hasElevator === true)
    ) {
      return {
        id: 'elevator',
        label: '역 승강기 접근성 확인',
        kind: 'advantage',
      };
    }
    if (
      stationElevatorSegments.length > 0
      && stationElevatorSegments.every((segment) => segment.hasElevator === false)
    ) {
      return {
        id: 'elevator',
        label: '역 승강기 없음',
        kind: 'caution',
      };
    }
    return null;
  }
  if (hasElevator) {
    return {
      id: 'elevator',
      label: '승강기 이용 가능',
      kind: 'advantage',
    };
  }
  if (elevatorUnavailable) {
    return null;
  }
  return null;
}

function lowFloorFact(status: RouteScore['lowFloorStatus']): V2RouteFact | null {
  switch (status) {
    case 'confirmed':
      return {
        id: 'low-floor',
        label: '저상버스',
        kind: 'advantage',
      };
    case 'regular':
      return {
        id: 'low-floor',
        label: '일반버스',
        kind: 'caution',
      };
    case 'unknown':
    case 'none':
      return null;
  }
}

function terrainFacts(route: RouteCandidate): V2RouteFact[] {
  const terrain = route.terrain;
  if (
    terrain?.status === 'estimated_90m' &&
    terrain.avgSlopePercent !== undefined
  ) {
    const avgText = formatSlopePercent(terrain.avgSlopePercent);
    if (avgText === null) return [];
    // avg = |grade| 가중평균. "최대"는 min·max가 모두 있을 때만
    // max(|max|, |min|) — 부호 있는 max만 쓰면 평균보다 작아 보일 수 있다.
    const peak = resolvePeakSlopePercent(
      terrain.maxSlopePercent,
      terrain.minSlopePercent,
    );
    const peakText = peak === null ? null : formatSlopePercent(peak);
    const label =
      peakText !== null
        ? `평균 경사 ${avgText}% · 최대 ${peakText}%`
        : `평균 경사 ${avgText}%`;
    const slopeLevel = resolveSlopeLevel(terrain.avgSlopePercent) ?? undefined;
    const gradeLabel = slopeLevel ? SLOPE_LEVEL_LABELS[slopeLevel] : undefined;
    const facts: V2RouteFact[] = [
      {
        id: 'terrain',
        label,
        kind: 'estimate',
        detail: terrain.source || undefined,
        slopeLevel,
        title: gradeLabel ? `${label}, ${gradeLabel}` : label,
      },
    ];
    if (
      terrain.elevationGainM !== undefined &&
      terrain.elevationGainM > 0
    ) {
      facts.push({
        id: 'elevation-gain',
        label: `누적 오르막 ${Math.round(terrain.elevationGainM)}m`,
        kind: 'estimate',
      });
    }
    return facts;
  }

  return [];
}

function shadeFacts(route: RouteCandidate): V2RouteFact[] {
  const shade = route.shade;
  if (!shade) {
    return [];
  }

  if (shade.status === 'not_daylight' || shade.status === 'unavailable') {
    return [];
  }

  if (shade.shadeRatio === undefined) {
    return [];
  }

  const ratio = Math.round(shade.shadeRatio * 100);
  const facts: V2RouteFact[] = [
    {
      id: 'shade',
      label:
        shade.estimateKind === 'lower_bound'
          ? `확인된 건물 그늘 최소 ${ratio}%`
          : `건물 그늘 ${ratio}%`,
      kind: 'estimate',
      detail: `${shade.source} · ${shade.calculationNote}`,
    },
  ];

  if (shade.status === 'estimated_demo') {
    facts.push({
      id: 'shade-source',
      label: '건물 높이 반영',
      kind: 'neutral',
    });
  } else {
    const known = shade.knownHeightBuildingCount;
    const total = shade.buildingCount;
    facts.push({
      id: 'shade-source',
      label:
        known !== undefined && total !== undefined
          ? `공공 건물 높이 ${known}/${total}건 확인`
          : 'VWorld 공공 건물 높이 기준',
      kind: 'neutral',
    });
  }

  const exclusions: string[] = [];
  if (shade.includesTreeShade === false) exclusions.push('나무 그늘');
  if (shade.includesTerrainShadow === false) exclusions.push('지형 그림자');
  if (exclusions.length > 0) {
    facts.push({
      id: 'shade-exclusions',
      label: `${exclusions.join('·')} 제외 (건물 전용)`,
      kind: 'neutral',
    });
  }
  return facts;
}

export function buildRouteViewModel(
  item: ScoredRoute,
  rank: number,
  profile: ProfileId,
  peers: ScoredRoute[] = [item],
): V2RouteViewModel {
  const { route, score } = item;
  const scoreKind = score.scoreKind ?? 'rule_baseline';
  const profileLabel = PROFILES[profile].label;
  const peerRoutes = peers.length > 0 ? peers : [item];
  const canCompare = peerRoutes.length > 1;
  const scoreDisplay = resolveScoreDisplay(score.finalScore, scoreKind, {
    canCompare,
  });
  const { characteristicLabels, traitLabels } =
    resolveTraitAndCharacteristicLabels(route, canCompare);
  const unavailableTraits = (route.traitLabels ?? [])
    .filter((trait) => trait.evidenceStatus === 'unavailable')
    .map((trait) => trait.displayLabel);
  const facts = [
    stairFact(route),
    elevatorFact(route),
    lowFloorFact(score.lowFloorStatus),
    ...terrainFacts(route),
    ...shadeFacts(route),
  ].filter((fact): fact is V2RouteFact => fact !== null);
  const needsConfirmation = unique([
    ...unavailableTraits,
    ...facts
      .filter((fact) => fact.kind === 'unknown')
      .map((fact) => fact.label),
  ]);

  return {
    routeId: route.id,
    rank,
    profile,
    profileLabel,
    title: `${profileLabel} 맞춤 ${rank}순위`,
    summary: route.summary,
    meta: `${Math.round(route.totalDurationMin)}분 · 도보 ${route.totalWalkM}m · 환승 ${route.transferCount}회`,
    stats: {
      durationMin: Math.round(route.totalDurationMin),
      walkM: route.totalWalkM,
      transferCount: route.transferCount,
    },
    score: scoreDisplay,
    scoreKindLabel: SCORE_KIND_LABEL[scoreKind],
    characteristicLabels,
    traitLabels,
    facts,
    needsConfirmation,
    reasons: buildDisplayReasons(item, peers),
    cautions: [...score.cautions],
    voiceSummary: score.voiceSummary,
  };
}

const DISPLAY_REASON_FALLBACK =
  '경로 상세에서 이동 정보를 확인해 주세요';

/**
 * 화면에 보이는 경로 특징만 만든다.
 * 점수 임계값 추정 문구(score.reasons)는 쓰지 않고,
 * 경로 구조화 필드·후보 간 실제 비교·근거 있는 trait만 사용한다.
 * 동일 사실은 key로 한 번만 넣는다.
 */
export function buildDisplayReasons(
  item: ScoredRoute,
  peers: ScoredRoute[] = [item],
): string[] {
  const { route, score } = item;
  const out: string[] = [];
  const usedKeys = new Set<string>();
  const peerRoutes = peers.length > 0 ? peers : [item];
  const canCompare = peerRoutes.length > 1;

  const add = (key: string, text: string) => {
    if (usedKeys.has(key)) return;
    usedKeys.add(key);
    out.push(text);
  };

  const durationMin = Math.round(route.totalDurationMin);
  const walkM = route.totalWalkM;

  // 1) 환승: 0회는 절대 사실만. 비교 “가장 적어요(0회)”와 중복하지 않는다.
  if (route.transferCount === 0) {
    add('transfer', '환승 없이 이동해요.');
  } else if (canCompare) {
    const transfers = peerRoutes.map(({ route: peer }) => peer.transferCount);
    const minTransfer = Math.min(...transfers);
    if (
      route.transferCount === minTransfer
      && transfers.filter((value) => value === minTransfer).length === 1
      && Math.max(...transfers) > minTransfer
    ) {
      add('transfer', `후보 중 환승이 가장 적어요 (${route.transferCount}회).`);
    }
  }

  // 2) 시간·도보: 복수 후보에서만 최상급 비교, 단일/비교 실패 시 절대 사실
  if (canCompare) {
    const durations = peerRoutes.map(({ route: peer }) => peer.totalDurationMin);
    const walks = peerRoutes.map(({ route: peer }) => peer.totalWalkM);
    const minDuration = Math.min(...durations);
    const minWalk = Math.min(...walks);

    if (
      route.totalDurationMin === minDuration
      && durations.filter((value) => value === minDuration).length === 1
    ) {
      add('duration', `후보 중 소요시간이 가장 짧아요 (${durationMin}분).`);
    }
    if (
      route.totalWalkM === minWalk
      && walks.filter((value) => value === minWalk).length === 1
    ) {
      add('walk', `후보 중 도보가 가장 짧아요 (${walkM}m).`);
    }
  }

  // 3) 시설·지형·그늘 등 경로별 구조화 사실
  const stairs = stairFact(route);
  if (stairs?.kind === 'advantage') {
    add('stairs', '확인된 구간에서 계단이 없어요.');
  } else if (stairs?.kind === 'caution') {
    add(
      'stairs',
      stairs.label.startsWith('계단 ')
        ? `${stairs.label}가 있어요.`
        : '계단이 포함돼요.',
    );
  }

  const elevator = elevatorFact(route);
  if (elevator?.kind === 'advantage') {
    if (elevator.label === '승강기 이용 가능') {
      add('elevator', '승강기 이용이 확인됐어요.');
    } else if (elevator.label === '역 승강기 접근성 확인') {
      add('elevator', '역 승강기 접근성이 확인됐어요.');
    } else {
      add('elevator', `${elevator.label}예요.`);
    }
  }

  if (score.lowFloorStatus === 'confirmed') {
    add('lowFloor', '경로의 버스가 저상버스로 확인됐어요.');
  }

  const terrain = route.terrain;
  if (
    terrain?.status === 'estimated_90m'
    && terrain.avgSlopePercent !== undefined
  ) {
    const avgText = formatSlopePercent(terrain.avgSlopePercent);
    if (avgText !== null) {
      add('terrain', `평균 경사 ${avgText}%로 추정돼요.`);
    }
  }

  const shade = route.shade;
  if (
    shade
    && (shade.status === 'estimated_demo' || shade.status === 'estimated_public')
    && shade.shadeRatio !== undefined
  ) {
    const ratio = Math.round(shade.shadeRatio * 100);
    add(
      'shade',
      shade.estimateKind === 'lower_bound'
        ? `확인된 건물 그늘이 최소 ${ratio}%예요.`
        : `건물 그늘이 약 ${ratio}%로 추정돼요.`,
    );
  }

  const characteristicKey: Partial<
    Record<NonNullable<RouteCandidate['characteristics']>[number], string>
  > = {
    fastest: 'duration',
    shortest_walk: 'walk',
    fewest_transfers: 'transfer',
    stair_free: 'stairs',
    low_floor_confirmed: 'lowFloor',
    lowest_slope: 'terrain',
    most_shade: 'shade',
  };

  for (const characteristic of route.characteristics ?? []) {
    if (!canCompare && RELATIVE_CHARACTERISTICS.has(characteristic)) continue;
    const overlapKey = characteristicKey[characteristic];
    if (overlapKey && usedKeys.has(overlapKey)) continue;
    add(
      `characteristic:${characteristic}`,
      `${CHARACTERISTIC_LABEL[characteristic]}로 표시된 후보예요.`,
    );
  }

  // traitLabels의 "… 근거가 있어요."는 구체 사실이 없어 화면 근거로 쓰지 않는다.
  // 동일 주제(최단시간·도보 등)는 위 구조화 key로 이미 중복 제거된다.

  // 4) 아직 비어 있는 기본 절대 사실로 보강 (단일 후보·비교 탈락 시)
  if (!usedKeys.has('walk')) {
    add('walk', `도보 거리 ${walkM}m예요.`);
  }
  if (!usedKeys.has('duration')) {
    add('duration', `소요시간 ${durationMin}분이에요.`);
  }
  if (!usedKeys.has('transfer') && route.transferCount > 0) {
    add('transfer', `환승 ${route.transferCount}회예요.`);
  }

  const limited = out.slice(0, 3);
  return limited.length > 0 ? limited : [DISPLAY_REASON_FALLBACK];
}

/** 경로 sources 항목을 출처 안내 문장으로 정규화한다. */
export function formatRouteSourceLabel(source: string): string {
  const trimmed = source.trim();
  if (!trimmed) return trimmed;
  if (/^경로 제공\s*:/.test(trimmed)) return trimmed;

  const lower = trimmed.toLowerCase();
  if (lower === 'odsay') return '경로 제공: ODsay';
  if (lower === 'tmap' || lower === '티맵') return '경로 제공: TMAP';
  if (lower === 'kakao' || lower === '카카오') return '경로 제공: Kakao';

  return `경로 제공: ${trimmed}`;
}
