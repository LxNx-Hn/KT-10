import { describe, expect, it } from 'vitest';
import type {
  RouteCandidate,
  RouteScore,
  RouteSegment,
  ScoredRoute,
} from '@/types';
import {
  GENTLE_SLOPE_ABSOLUTE_LABEL,
  LOWEST_SLOPE_RELATIVE_LABEL,
  ROUTE_SCORE_DISCLAIMER,
  ROUTE_SCORE_DISCLAIMER_SINGLE,
  SCORE_UNAVAILABLE_LABEL,
  buildRouteViewModel,
  formatRouteSourceLabel,
  resolveScoreDisplay,
  routeScoreDisclaimer,
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
          minSlopePercent: -1.2,
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
          label: '평균 경사 2.34% · 최대 7.1%',
          kind: 'estimate',
          slopeLevel: 'moderate',
          title: '평균 경사 2.34% · 최대 7.1%, 보통',
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

  it('min 없이 max만 있으면 최대를 추측하지 않고 평균만 표시한다', () => {
    const view = buildRouteViewModel(
      makeItem({
        terrain: {
          status: 'estimated_90m',
          avgSlopePercent: 1.8,
          maxSlopePercent: 4.5,
          source: 'Copernicus GLO-90',
          resolutionM: 90,
        },
      }),
      1,
      'general',
    );

    expect(view.facts.find((fact) => fact.id === 'terrain')).toMatchObject({
      label: '평균 경사 1.8%',
      kind: 'estimate',
      slopeLevel: 'gentle',
      title: '평균 경사 1.8%, 완만',
      detail: 'Copernicus GLO-90',
    });
    expect(view.facts.find((fact) => fact.id === 'terrain')?.label).not.toContain(
      '최대',
    );
  });

  it('평균 |grade|와 부호 max/min이 달라도 최대는 절댓값 극값으로 표시한다', () => {
    const view = buildRouteViewModel(
      makeItem({
        terrain: {
          status: 'estimated_90m',
          avgSlopePercent: 8,
          maxSlopePercent: 4.5,
          minSlopePercent: -12,
          source: 'test',
          resolutionM: 90,
        },
      }),
      1,
      'general',
    );

    expect(view.facts.find((fact) => fact.id === 'terrain')).toMatchObject({
      label: '평균 경사 8% · 최대 12%',
      slopeLevel: 'steep',
      title: '평균 경사 8% · 최대 12%, 급경사',
    });
  });

  it('경계값 표시 정밀도와 등급색이 모순되지 않는다', () => {
    const atBoundary = buildRouteViewModel(
      makeItem({
        terrain: {
          status: 'estimated_90m',
          avgSlopePercent: 8,
          maxSlopePercent: 8,
          minSlopePercent: -3,
          source: 'test',
          resolutionM: 90,
        },
      }),
      1,
      'general',
    );
    expect(atBoundary.facts.find((f) => f.id === 'terrain')).toMatchObject({
      label: '평균 경사 8% · 최대 8%',
      slopeLevel: 'steep',
    });

    const justOver = buildRouteViewModel(
      makeItem({
        terrain: {
          status: 'estimated_90m',
          avgSlopePercent: 8.01,
          maxSlopePercent: 8.01,
          minSlopePercent: -1,
          source: 'test',
          resolutionM: 90,
        },
      }),
      1,
      'general',
    );
    expect(justOver.facts.find((f) => f.id === 'terrain')).toMatchObject({
      label: '평균 경사 8.01% · 최대 8.01%',
      slopeLevel: 'very-steep',
    });
  });

  describe('경사 특성 배지 (상대 비교 vs 절대 완만)', () => {
    it('평균 2% 이하이고 비교 배지가 없으면 절대 완만만 표시한다', () => {
      const view = buildRouteViewModel(
        makeItem({
          terrain: {
            status: 'estimated_90m',
            avgSlopePercent: 2,
            maxSlopePercent: 1.5,
            minSlopePercent: -1.2,
            source: 'test',
            resolutionM: 90,
          },
        }),
        1,
        'general',
      );

      expect(view.characteristicLabels).not.toContain(LOWEST_SLOPE_RELATIVE_LABEL);
      expect(view.traitLabels).toContain(GENTLE_SLOPE_ABSOLUTE_LABEL);
      expect(view.traitLabels).not.toContain('경사가 가장 완만한 길');
    });

    it('평균 2% 초과면 절대 완만 배지를 표시하지 않는다', () => {
      const view = buildRouteViewModel(
        makeItem({
          terrain: {
            status: 'estimated_90m',
            avgSlopePercent: 7.3,
            maxSlopePercent: 29.6,
            minSlopePercent: -4,
            source: 'test',
            resolutionM: 90,
          },
          traitLabels: [
            {
              labelId: 'gentle_slope',
              displayLabel: '경사가 완만한 길',
              evidenceStatus: 'derived',
              evidence: [],
            },
          ],
        }),
        1,
        'general',
      );

      expect(view.traitLabels).not.toContain(GENTLE_SLOPE_ABSOLUTE_LABEL);
      expect(view.characteristicLabels).not.toContain(GENTLE_SLOPE_ABSOLUTE_LABEL);
      expect(view.facts.find((fact) => fact.id === 'terrain')?.label).toBe(
        '평균 경사 7.3% · 최대 29.6%',
      );
    });

    it('후보 내 최저 구간 최대 경사면 상대 비교 문구를 표시한다', () => {
      const primary = makeItem({
        characteristics: ['lowest_slope'],
        terrain: {
          status: 'estimated_90m',
          avgSlopePercent: 7.3,
          maxSlopePercent: 29.6,
          minSlopePercent: -4,
          elevationGainM: 128,
          source: 'test',
          resolutionM: 90,
        },
        traitLabels: [
          {
            labelId: 'lowest_slope',
            displayLabel: '경사가 완만한 길',
            evidenceStatus: 'derived',
            evidence: [
              {
                feature: 'max_slope_percent',
                value: 29.6,
                unit: 'percent',
                source: 'elevation',
              },
            ],
          },
        ],
      });
      const peer = makeItem();
      peer.route.id = 'peer-b';
      const view = buildRouteViewModel(primary, 1, 'general', [primary, peer]);

      const slopeLabels = [
        ...view.characteristicLabels,
        ...view.traitLabels,
      ].filter(
        (label) =>
          label === LOWEST_SLOPE_RELATIVE_LABEL
          || label === GENTLE_SLOPE_ABSOLUTE_LABEL
          || label === '경사가 가장 완만한 길'
          || label === '경사가 완만한 길',
      );

      expect(slopeLabels).toEqual([LOWEST_SLOPE_RELATIVE_LABEL]);
      expect(view.facts.find((fact) => fact.id === 'terrain')?.label).toBe(
        '평균 경사 7.3% · 최대 29.6%',
      );
      expect(view.facts.find((fact) => fact.id === 'elevation-gain')?.label).toBe(
        '누적 오르막 128m',
      );
    });

    it('상대 비교와 절대 완만 배지가 한 카드에 중복되지 않는다', () => {
      const primary = makeItem({
        characteristics: ['lowest_slope'],
        terrain: {
          status: 'estimated_90m',
          avgSlopePercent: 1.5,
          maxSlopePercent: 1.8,
          minSlopePercent: -1,
          source: 'test',
          resolutionM: 90,
        },
        traitLabels: [
          {
            labelId: 'lowest_slope',
            displayLabel: '경사가 완만한 길',
            evidenceStatus: 'derived',
            evidence: [],
          },
          {
            labelId: 'gentle_slope',
            displayLabel: '경사가 완만한 길',
            evidenceStatus: 'derived',
            evidence: [],
          },
        ],
      });
      const peer = makeItem();
      peer.route.id = 'peer-steep';
      const view = buildRouteViewModel(primary, 1, 'general', [primary, peer]);

      const slopeLabels = [
        ...view.characteristicLabels,
        ...view.traitLabels,
      ].filter(
        (label) =>
          label.includes('경사') && !label.startsWith('평균 경사'),
      );
      expect(slopeLabels).toEqual([LOWEST_SLOPE_RELATIVE_LABEL]);
    });

    it('후보가 1개면 상대 비교 배지를 숨기고 절대 완만만 허용한다', () => {
      const alone = buildRouteViewModel(
        makeItem({
          characteristics: ['lowest_slope', 'fastest', 'fewest_transfers'],
          terrain: {
            status: 'estimated_90m',
            avgSlopePercent: 1.2,
            maxSlopePercent: 1.5,
            minSlopePercent: -0.8,
            source: 'test',
            resolutionM: 90,
          },
          traitLabels: [
            {
              labelId: 'lowest_slope',
              displayLabel: '경사가 완만한 길',
              evidenceStatus: 'derived',
              evidence: [{ feature: 'max_slope_percent', value: 1.5, source: 't' }],
            },
          ],
        }),
        1,
        'general',
        // peers 기본값 = 자기 자신만 → 비교 불가
      );

      expect(alone.characteristicLabels).not.toContain(LOWEST_SLOPE_RELATIVE_LABEL);
      expect(alone.characteristicLabels).not.toContain('제일 빠른 길');
      expect(alone.characteristicLabels).not.toContain('환승이 가장 적은 길');
      expect(alone.traitLabels).toContain(GENTLE_SLOPE_ABSOLUTE_LABEL);
      expect(alone.traitLabels.join(' ')).not.toContain('후보 중');
      expect(alone.facts.find((f) => f.id === 'terrain')?.label).toContain('평균 경사');
      expect(alone.score.ariaLabel).toContain('산정한 점수');
      expect(alone.score.ariaLabel).not.toContain('후보 경로를 비교');
    });

    it('null/undefined 경사값에서도 오류 없이 경사 특성 배지를 생략한다', () => {
      expect(() =>
        buildRouteViewModel(
          makeItem({
            terrain: { status: 'unavailable' },
            traitLabels: [
              {
                labelId: 'gentle_slope',
                displayLabel: '경사가 완만한 길',
                evidenceStatus: 'derived',
                evidence: [],
              },
            ],
          }),
          1,
          'general',
        ),
      ).not.toThrow();

      const view = buildRouteViewModel(
        makeItem({
          terrain: undefined,
          characteristics: undefined,
          traitLabels: undefined,
        }),
        1,
        'general',
      );
      expect(view.traitLabels).not.toContain(GENTLE_SLOPE_ABSOLUTE_LABEL);
      expect(view.characteristicLabels).not.toContain(LOWEST_SLOPE_RELATIVE_LABEL);
    });
  });

  it('unavailable 그늘과 unavailable trait을 0%가 아닌 확인필요로 분리한다', () => {
    const view = buildRouteViewModel(
      makeItem({
        shade: shade('unavailable', {
          calculationNote: '',
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
    ['rule_baseline', '맞춤 적합도'],
    ['bootstrap_baseline', '맞춤 적합도'],
    ['human_model', '맞춤 적합도'],
  ] as const)('%s 점수 종류를 맞춤 적합도로 표시한다', (scoreKind, label) => {
    const view = buildRouteViewModel(
      makeItem({ scoreKind }),
      3,
      'youth',
    );

    expect(view.score).toMatchObject({
      available: true,
      value: 78.6,
      rounded: 79,
      kind: scoreKind,
      summaryLabel: '맞춤 적합도 79점',
    });
    expect(view.score.ariaLabel).toContain('맞춤 적합도 79점');
    // peers 기본값 1개 → 단일 후보 산정 문구
    expect(view.score.ariaLabel).toContain('산정한 점수');
    expect(view.scoreKindLabel).toBe(label);
    expect(view.profileLabel).toBe('청소년');
    expect(view.stats).toEqual({
      durationMin: 18,
      walkM: 420,
      transferCount: 1,
    });
    expect(routeScoreDisclaimer(2)).toBe(ROUTE_SCORE_DISCLAIMER);
    expect(routeScoreDisclaimer(1)).toBe(ROUTE_SCORE_DISCLAIMER_SINGLE);
    expect(ROUTE_SCORE_DISCLAIMER).not.toMatch(/안전 점수|안전도/);
    expect(ROUTE_SCORE_DISCLAIMER_SINGLE).not.toContain('후보 경로를 비교');
  });

  describe('맞춤 적합도 표시', () => {
    it('100점과 실제 0점을 맞춤 적합도로 표시한다', () => {
      expect(resolveScoreDisplay(100).summaryLabel).toBe('맞춤 적합도 100점');
      expect(resolveScoreDisplay(0).summaryLabel).toBe('맞춤 적합도 0점');
      expect(resolveScoreDisplay(0).available).toBe(true);
      expect(resolveScoreDisplay(0).rounded).toBe(0);
    });

    it('null/undefined/NaN을 0점으로 오인하지 않는다', () => {
      for (const bad of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY]) {
        const display = resolveScoreDisplay(bad);
        expect(display.available).toBe(false);
        expect(display.rounded).toBeNull();
        expect(display.summaryLabel).toBe(SCORE_UNAVAILABLE_LABEL);
        expect(display.summaryLabel).not.toContain('0점');
      }
    });

    it('절대 안전 표현을 쓰지 않는다', () => {
      const view = buildRouteViewModel(makeItem({ scoreKind: 'human_model' }), 1, 'general');
      const blob = JSON.stringify(view);
      expect(blob).not.toContain('안전 점수');
      expect(blob).not.toContain('안전도');
      expect(blob).not.toContain('완벽한 경로');
      expect(blob).not.toContain('가장 안전한 경로');
      expect(view.score.summaryLabel).toBe('맞춤 적합도 79점');
    });
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
    const primary = makeItem({
      segments: [
        {
          ...BASE_SEGMENT,
          mode: 'transfer',
          needsVerticalMove: true,
        },
      ],
      lowFloorStatus: 'unknown',
      characteristics: ['fastest'],
    });
    const peer = makeItem();
    peer.route.id = 'peer-slower';
    peer.route.totalDurationMin = 40;
    const view = buildRouteViewModel(primary, 1, 'disabled', [primary, peer]);

    expect(view.characteristicLabels).toEqual(['제일 빠른 길']);
    expect(view.facts.find((f) => f.id === 'elevator')).toBeUndefined();
    expect(view.facts.find((f) => f.id === 'low-floor')).toBeUndefined();
  });

  it('점수 추정 추천 이유 대신 구조화 근거만 표시한다', () => {
    const bare = buildRouteViewModel(makeItem({
      // score.reasons는 "보행 부담을 비교했습니다."지만 구조화 비교 근거는 없음
    }), 1, 'general');
    expect(bare.reasons).toEqual([
      '도보 거리 420m예요.',
      '소요시간 18분이에요.',
      '환승 1회예요.',
    ]);
    expect(bare.reasons.join(' ')).not.toMatch(/가장 |안전|편안|비교적/);

    const evidenced = buildRouteViewModel(
      makeItem({
        segments: [{
          ...BASE_SEGMENT,
          hasStairs: false,
          stairsCount: 0,
        }],
        lowFloorStatus: 'confirmed',
        terrain: {
          status: 'estimated_90m',
          avgSlopePercent: 1.5,
          source: 'test',
          resolutionM: 90,
        },
      }),
      1,
      'general',
    );
    expect(evidenced.reasons).toEqual(
      expect.arrayContaining([
        '확인된 구간에서 계단이 없어요.',
        '경로의 버스가 저상버스로 확인됐어요.',
        '평균 경사 1.5%로 추정돼요.',
      ]),
    );
    expect(evidenced.reasons.join(' ')).not.toContain(
      '보행 부담을 비교했습니다.',
    );
    expect(evidenced.reasons.join(' ')).not.toMatch(/가장 /);
  });

  it('후보가 1개면 절대 사실만, 복수일 때만 실제 비교 표현을 쓴다', () => {
    const short = makeItem({
      segments: [BASE_SEGMENT],
    });
    short.route.id = 'short';
    short.route.totalDurationMin = 10;
    short.route.totalWalkM = 100;
    short.route.transferCount = 0;
    short.score.routeId = 'short';
    short.score.reasons = ['후보 중 소요시간이 가장 짧은 편이에요.'];

    const long = makeItem({
      segments: [BASE_SEGMENT],
    });
    long.route.id = 'long';
    long.route.totalDurationMin = 30;
    long.route.totalWalkM = 800;
    long.route.transferCount = 2;
    long.score.routeId = 'long';
    long.score.reasons = ['현재 날씨 조건에서 비교적 안전해요.'];

    const alone = buildRouteViewModel(short, 1, 'general', [short]);
    expect(alone.reasons.join(' ')).not.toMatch(/가장 /);
    expect(alone.characteristicLabels.join(' ')).not.toMatch(/가장 |제일 |후보 중/);
    expect(alone.reasons).toEqual(
      expect.arrayContaining([
        '환승 없이 이동해요.',
        '도보 거리 100m예요.',
        '소요시간 10분이에요.',
      ]),
    );

    const compared = buildRouteViewModel(short, 1, 'general', [short, long]);
    expect(compared.reasons).toEqual(
      expect.arrayContaining([
        '환승 없이 이동해요.',
        '후보 중 소요시간이 가장 짧아요 (10분).',
        '후보 중 도보가 가장 짧아요 (100m).',
      ]),
    );
    expect(compared.reasons.join(' ')).not.toContain('환승이 가장 적어요');
    expect(compared.reasons.join(' ')).not.toContain('비교적 안전');
  });

  it('동일 사실 특징은 한 번만 표시한다', () => {
    const zeroTransfer = makeItem();
    zeroTransfer.route.transferCount = 0;
    zeroTransfer.route.characteristics = ['fewest_transfers', 'shortest_walk'];
    const peer = makeItem();
    peer.route.id = 'peer';
    peer.route.totalWalkM = 900;
    peer.route.transferCount = 2;
    peer.score.routeId = 'peer';

    const reasons = buildRouteViewModel(
      zeroTransfer,
      1,
      'general',
      [zeroTransfer, peer],
    ).reasons;
    const transferLines = reasons.filter((line) => line.includes('환승'));
    expect(transferLines).toEqual(['환승 없이 이동해요.']);
    expect(reasons.join(' ')).not.toContain('환승이 가장 적어요');
    expect(reasons.filter((line) => line.includes('도보')).length).toBe(1);
  });

  it('경로 출처 라벨을 정규화한다', () => {
    expect(formatRouteSourceLabel('odsay')).toBe('경로 제공: ODsay');
    expect(formatRouteSourceLabel('경로 제공: ODsay')).toBe('경로 제공: ODsay');
  });
});
