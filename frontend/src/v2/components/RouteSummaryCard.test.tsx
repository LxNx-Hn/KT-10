// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ScoredRoute } from '@/types';
import { buildRouteViewModel } from '../routeViewModel';
import RouteSummaryCard from './RouteSummaryCard';

afterEach(() => {
  cleanup();
});

function makeItem(overrides: Partial<ScoredRoute['route']> = {}): ScoredRoute {
  return {
    route: {
      id: 'route-a',
      summary: '버스 1001 · 서면역',
      origin: '출발',
      destination: '도착',
      segments: [{
        id: 'w1',
        mode: 'walk',
        description: '도보',
        durationMin: 6,
        hasStairs: false,
        stairsCount: 0,
      }],
      totalDurationMin: 24,
      totalWalkM: 380,
      transferCount: 1,
      characteristics: ['fastest'],
      terrain: {
        status: 'estimated_90m',
        avgSlopePercent: 3.2,
        maxSlopePercent: 5.1,
        minSlopePercent: -1.2,
        source: 'test',
      },
      ...overrides,
    },
    score: {
      routeId: 'route-a',
      components: {},
      display: {},
      finalScore: 88,
      scoreKind: 'rule_baseline',
      lowFloorStatus: 'none',
      reasons: [],
      cautions: [],
      voiceSummary: '24분 경로',
    },
  };
}

describe('RouteSummaryCard 정보 위계', () => {
  it('소요 시간·추천 근거·상세 CTA를 순서대로 노출하고 선택은 route id를 유지한다', () => {
    const item = makeItem();
    const peer = makeItem({
      id: 'route-b',
      summary: '지하철 1호선',
      totalDurationMin: 30,
      totalWalkM: 500,
      transferCount: 2,
      characteristics: ['fewest_transfers'],
    });
    const view = buildRouteViewModel(item, 1, 'general', [item, peer]);
    const onSelect = vi.fn();
    const onDetails = vi.fn();

    const { container } = render(
      <RouteSummaryCard
        view={view}
        selected
        refining={false}
        onSelect={onSelect}
        onDetails={onDetails}
      />,
    );

    const card = container.querySelector('.map-first__route-card');
    expect(card?.getAttribute('data-route-id')).toBe('route-a');
    expect(card?.getAttribute('aria-current')).toBe('true');
    expect(card?.textContent).toContain('1순위');
    expect(card?.textContent).toContain('버스 1001 · 서면역');
    expect(
      card?.querySelector('.map-first__route-card-duration')?.textContent,
    ).toMatch(/24\s*분/);
    expect(
      card?.querySelector('.map-first__route-score')?.textContent,
    ).toContain('맞춤 적합도 88점');
    expect(
      card?.querySelector('.map-first__route-stats')?.textContent,
    ).toMatch(/380\s*m 도보/);
    expect(
      card?.querySelector('.map-first__route-stats')?.textContent,
    ).toMatch(/1\s*회 환승/);
    expect(
      card?.querySelector('.map-first__route-card-reasons')?.textContent,
    ).toBeTruthy();
    // 순위 문구를 경로명 아래에 중복하지 않는다.
    expect(card?.textContent).not.toContain('일반 맞춤 1순위');

    fireEvent.click(card!);
    expect(onSelect).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: '상세 정보 보기' }));
    expect(onDetails).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it('데이터가 일부 없어도 렌더링 오류 없이 상세 버튼을 유지한다', () => {
    const item = makeItem({
      terrain: undefined,
      characteristics: undefined,
      traitLabels: undefined,
    });
    item.score.finalScore = Number.NaN;
    const view = buildRouteViewModel(item, 2, 'elderly', [item]);

    render(
      <RouteSummaryCard
        view={view}
        selected={false}
        refining={false}
        onSelect={() => undefined}
        onDetails={() => undefined}
      />,
    );

    expect(screen.getByRole('button', { name: '상세 정보 보기' })).toBeTruthy();
    expect(screen.getByText('적합도 산정 불가')).toBeTruthy();
    expect(screen.getByText(/2순위/)).toBeTruthy();
  });
});
