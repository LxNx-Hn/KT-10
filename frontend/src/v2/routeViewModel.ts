import { PROFILES } from '@/config/profiles';
import type {
  ProfileId,
  RouteCandidate,
  RouteScore,
  ScoredRoute,
} from '@/types';

export const ROUTE_SCORE_DISCLAIMER =
  '적합 점수는 후보 경로끼리 비교하기 위한 값이며 안전도나 성공 확률이 아닙니다.';

export const SCORE_KIND_LABEL: Record<
  NonNullable<RouteScore['scoreKind']>,
  string
> = {
  rule_baseline: '프로필 적합 점수',
  bootstrap_baseline: '프로필 적합 점수',
  human_model: '프로필 적합 점수',
};

const CHARACTERISTIC_LABEL: Record<
  NonNullable<RouteCandidate['characteristics']>[number],
  string
> = {
  fastest: '제일 빠른 길',
  shortest_walk: '도보가 가장 짧은 길',
  lowest_slope: '경사가 가장 완만한 길',
  most_shade: '건물 그늘이 가장 많은 길',
  fewest_transfers: '환승이 가장 적은 길',
  stair_free: '계단 없음',
  low_floor_confirmed: '저상버스 이용 가능',
};

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
  score: {
    value: number;
    rounded: number;
    kind: NonNullable<RouteScore['scoreKind']>;
  };
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
    const detail = [
      terrain.maxSlopePercent !== undefined
        ? `최대 ${terrain.maxSlopePercent.toFixed(1)}%`
        : undefined,
      terrain.source,
    ]
      .filter((value): value is string => Boolean(value))
      .join(' · ');
    const facts: V2RouteFact[] = [
      {
        id: 'terrain',
        label: `평균 경사 ${terrain.avgSlopePercent.toFixed(1)}%`,
        kind: 'estimate',
        detail: detail || undefined,
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
  const characteristicLabels = unique(
    (route.characteristics ?? []).map(
      (characteristic) => CHARACTERISTIC_LABEL[characteristic],
    ),
  );
  const traitLabels = unique(
    (route.traitLabels ?? [])
      .filter((trait) => trait.evidenceStatus !== 'unavailable')
      .map((trait) => trait.displayLabel),
  );
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
    score: {
      value: score.finalScore,
      rounded: Math.round(score.finalScore),
      kind: scoreKind,
    },
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
    add(
      'terrain',
      `평균 경사 ${terrain.avgSlopePercent.toFixed(1)}%로 추정돼요.`,
    );
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
    const overlapKey = characteristicKey[characteristic];
    if (overlapKey && usedKeys.has(overlapKey)) continue;
    add(
      `characteristic:${characteristic}`,
      `${CHARACTERISTIC_LABEL[characteristic]}로 표시된 후보예요.`,
    );
  }

  for (const trait of route.traitLabels ?? []) {
    if (trait.evidenceStatus === 'unavailable') continue;
    if (trait.evidence.length === 0) continue;
    add(`trait:${trait.labelId}`, `${trait.displayLabel} 근거가 있어요.`);
  }

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

  const limited = out.slice(0, 4);
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
