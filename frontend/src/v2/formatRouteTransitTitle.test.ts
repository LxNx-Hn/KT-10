import { describe, expect, it } from 'vitest';
import { formatRouteTransitTitle } from './formatRouteTransitTitle';
import type { V2TransitStep } from './routeViewModel';

describe('formatRouteTransitTitle', () => {
  it('도보만 있으면 도보로 표시한다', () => {
    expect(
      formatRouteTransitTitle(
        [{ id: 'w', mode: 'walk', modeLabel: '도보', durationMin: 12 }],
        '도보 + 12',
      ),
    ).toBe('도보');
  });

  it('버스·지하철은 routeLabel이 있으면 함께 표시하고 없으면 fallback한다', () => {
    expect(
      formatRouteTransitTitle(
        [
          { id: 'w', mode: 'walk', modeLabel: '도보', durationMin: 2 },
          {
            id: 'b',
            mode: 'bus',
            modeLabel: '버스',
            durationMin: 56,
            routeLabel: '59번',
          },
          { id: 'w2', mode: 'walk', modeLabel: '도보', durationMin: 1 },
        ],
        '도보 + 59',
      ),
    ).toBe('버스 59번');

    expect(
      formatRouteTransitTitle(
        [
          {
            id: 's',
            mode: 'subway',
            modeLabel: '지하철',
            durationMin: 18,
            routeLabel: '1호선',
            subwayLineId: 'busan-1',
          },
        ],
        '도보 + 1',
      ),
    ).toBe('지하철 1호선');

    expect(
      formatRouteTransitTitle(
        [{ id: 'b', mode: 'bus', modeLabel: '버스', durationMin: 10 }],
        '도보 + 버스',
      ),
    ).toBe('버스');
  });

  it('복수 버스와 복합 transit을 순서대로 join한다', () => {
    expect(
      formatRouteTransitTitle(
        [
          {
            id: 'b1',
            mode: 'bus',
            modeLabel: '버스',
            durationMin: 42,
            routeLabel: '3006번',
          },
          {
            id: 'b2',
            mode: 'bus',
            modeLabel: '버스',
            durationMin: 63,
            routeLabel: '58-2번',
          },
          {
            id: 'b3',
            mode: 'bus',
            modeLabel: '버스',
            durationMin: 67,
            routeLabel: '1001(심야)번',
          },
        ] satisfies V2TransitStep[],
        '도보 + 3006 + 58-2 + 1001(심야)',
      ),
    ).toBe('버스 3006번 · 버스 58-2번 · 버스 1001(심야)번');

    expect(
      formatRouteTransitTitle(
        [
          {
            id: 'b',
            mode: 'bus',
            modeLabel: '버스',
            durationMin: 20,
            routeLabel: '59번',
          },
          {
            id: 's',
            mode: 'subway',
            modeLabel: '지하철',
            durationMin: 15,
            routeLabel: '1호선',
            subwayLineId: 'busan-1',
          },
        ],
        '도보 + 복합',
      ),
    ).toBe('버스 59번 · 지하철 1호선');
  });
});
