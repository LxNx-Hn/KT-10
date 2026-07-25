import { describe, expect, it } from 'vitest';
import type {
  RouteCandidate,
  RouteScore,
  RouteSegment,
  ScoredRoute,
} from '@/types';
import {
  ROUTE_SCORE_DISCLAIMER,
  buildRouteViewModel,
} from './routeViewModel';

const BASE_SEGMENT: RouteSegment = {
  id: 'walk-1',
  mode: 'walk',
  description: '보행',
  durationMin: 8,
};

function makeItem({
  segments = [BASE_SEGMENT],
  shade,
  terrain,
  characteristics,
  traitLabels,
  scoreKind,
  lowFloorStatus = 'none',
}: {
  segments?: RouteSegment[];
  shade?: RouteCandidate['shade'];
  terrain?: RouteCandidate['terrain'];
  characteristics?: RouteCandidate['characteristics'];
  traitLabels?: RouteCandidate['traitLabels'];
  scoreKind?: RouteScore['scoreKind'];
  lowFloorStatus?: RouteScore['lowFloorStatus'];
} = {}): ScoredRoute {
  return {
    route: {
      id: 'route-1',
      summary: '도보 중심 경로',
      origin: '출발지',
      destination: '도착지',
      segments,
      totalDurationMin: 18,
      totalWalkM: 420,
      transferCount: 1,
      characteristics,
      traitLabels,
      terrain,
      shade,
    },
    score: {
      routeId: 'route-1',
      components: {},
      display: {},
      finalScore: 78.6,
      scoreKind,
      lowFloorStatus,
      reasons: ['보행 부담을 비교했습니다.'],
      cautions: [],
      voiceSummary: '18분이 걸리는 경로입니다.',
    },
  };
}

function shade(
  status: NonNullable<RouteCandidate['shade']>['status'],
  extra: Partial<NonNullable<RouteCandidate['shade']>> = {},
): NonNullable<RouteCandidate['shade']> {
  return {
    status,
    evaluatedAt: '2026-07-24T14:00:00+09:00',
    includesTreeShade: false,
    includesTerrainShadow: false,
    source: '테스트 건물 데이터',
    dataQuality: status === 'estimated_public' ? 'public' : 'demo',
    shadowPolygons: [],
    pathSegments: [],
    calculationNote: '테스트 계산 설명',
    ...extra,
  };
}

describe('v2 경로 표시 모델', () => {
  it('계단 정보가 미확인이면 배지를 노출하지 않는다', () => {
    const view = buildRouteViewModel(makeItem(), 1, 'general');
    const stairs = view.facts.find((fact) => fact.id === 'stairs');

    expect(stairs).toBeUndefined();
    expect(view.facts.map((fact) => fact.label)).not.toContain(
      '계단 없음 확인',
    );
  });

  it('hasStairs가 없어도 양수 stairsCount를 계단 있음으로 표시한다', () => {
    const view = buildRouteViewModel(
      makeItem({
        segments: [{ ...BASE_SEGMENT, stairsCount: 3 }],
      }),
      1,
      'disabled',
    );

    expect(view.facts.find((fact) => fact.id === 'stairs')).toMatchObject({
      label: '계단 3개',
      kind: 'caution',
    });
  });

  it('수직이동 여부를 추정하지 않고 확인된 역사 승강기 접근성은 별도로 표시한다', () => {
    const view = buildRouteViewModel(
      makeItem({
        segments: [{
          ...BASE_SEGMENT,
          id: 'subway-1',
          mode: 'subway',
          stationName: '부산역',
          hasElevator: true,
        }],
      }),
      1,
      'disabled',
    );

    expect(view.facts.find((fact) => fact.id === 'elevator')).toMatchObject({
      label: '역 승강기 접근성 확인',
      kind: 'advantage',
    });
  });

  it('공공 건물 그늘 lower bound와 90m 지형 추정을 수치 그대로 구분한다', () => {
    const view = buildRouteViewModel(
      makeItem({
        terrain: {
          status: 'estimated_90m',
          avgSlopePercent: 2.34,
          maxSlopePercent: 7.1,
          elevationGainM: 11.8,
          source: 'Copernicus GLO-90',
          resolutionM: 90,
        },
        shade: shade('estimated_public', {
          shadeRatio: 0.594,
          estimateKind: 'lower_bound',
          buildingCount: 12,
          knownHeightBuildingCount: 7,
          dataQuality: 'public',
        }),
      }),
      2,
      'elderly',
    );

    expect(view.facts).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          label: '평균 경사 2.3%',
          kind: 'estimate',
        }),
        expect.objectContaining({
          label: '확인된 건물 그늘 최소 59%',
          kind: 'estimate',
        }),
        expect.objectContaining({
          label: '공공 건물 높이 7/12건 확인',
        }),
      ]),
    );
  });

  it('unavailable 그늘과 unavailable trait을 0%가 아닌 확인필요로 분리한다', () => {
    const view = buildRouteViewModel(
      makeItem({
        shade: shade('unavailable', {
          calculationNote: '건물 데이터의 검증 범위를 벗어났습니다.',
        }),
        traitLabels: [
          {
            labelId: 'slope-unknown',
            displayLabel: '완만한 경사',
            evidenceStatus: 'unavailable',
            evidence: [],
          },
          {
            labelId: 'fast',
            displayLabel: '빠른 도착',
            evidenceStatus: 'observed',
            evidence: [],
          },
        ],
      }),
      1,
      'pregnant',
    );

    expect(view.traitLabels).toEqual(['빠른 도착']);
    expect(view.needsConfirmation).toEqual(['완만한 경사']);
    expect(view.facts.find((fact) => fact.id === 'shade')).toBeUndefined();
    expect(JSON.stringify(view)).not.toContain('그늘 0%');
  });

  it.each([
    ['rule_baseline', '프로필 적합 점수'],
    ['bootstrap_baseline', '프로필 적합 점수'],
    ['human_model', '프로필 적합 점수'],
  ] as const)('%s 점수 종류를 명시한다', (scoreKind, label) => {
    const view = buildRouteViewModel(
      makeItem({ scoreKind }),
      3,
      'youth',
    );

    expect(view.score).toEqual({
      value: 78.6,
      rounded: 79,
      kind: scoreKind,
    });
    expect(view.scoreKindLabel).toBe(label);
    expect(view.profileLabel).toBe('청소년');
    expect(view.stats).toEqual({
      durationMin: 18,
      walkM: 420,
      transferCount: 1,
    });
    expect(ROUTE_SCORE_DISCLAIMER).toContain('안전도나 성공 확률이 아닙니다');
  });

  it('데모 그늘과 야간 미계산 상태를 서로 다른 사실로 표시한다', () => {
    const demo = buildRouteViewModel(
      makeItem({
        shade: shade('estimated_demo', {
          shadeRatio: 0.4,
          estimateKind: 'estimate',
        }),
      }),
      1,
      'child',
    );
    const night = buildRouteViewModel(
      makeItem({ shade: shade('not_daylight') }),
      1,
      'child',
    );

    expect(demo.facts).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ label: '건물 그늘 40%', kind: 'estimate' }),
        expect.objectContaining({ label: '건물 높이 반영' }),
      ]),
    );
    expect(night.facts.find((fact) => fact.id === 'shade')).toBeUndefined();
  });

  it('승강기와 저상버스 미확인을 팩트에 노출하지 않는다', () => {
    const view = buildRouteViewModel(
      makeItem({
        segments: [
          {
            ...BASE_SEGMENT,
            mode: 'transfer',
            needsVerticalMove: true,
          },
        ],
        lowFloorStatus: 'unknown',
        characteristics: ['fastest'],
      }),
      1,
      'disabled',
    );

    expect(view.characteristicLabels).toEqual(['제일 빠른 길']);
    expect(view.facts.find((f) => f.id === 'elevator')).toBeUndefined();
    expect(view.facts.find((f) => f.id === 'low-floor')).toBeUndefined();
  });
});
