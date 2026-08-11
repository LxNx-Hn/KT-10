// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ProfileId, ScoredRoute } from '@/types';
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

function renderCard(
  profile: ProfileId,
  itemOverrides: Partial<ScoredRoute['route']> = {},
  handlers?: { onSelect?: () => void; onDetails?: () => void },
) {
  const item = makeItem(itemOverrides);
  const peer = makeItem({
    id: 'route-b',
    summary: '지하철 1호선',
    totalDurationMin: 30,
    totalWalkM: 500,
    transferCount: 2,
    characteristics: ['fewest_transfers'],
  });
  const view = buildRouteViewModel(item, 1, profile, [item, peer]);
  const onSelect = handlers?.onSelect ?? vi.fn();
  const onDetails = handlers?.onDetails ?? vi.fn();
  const result = render(
    <RouteSummaryCard
      view={view}
      selected
      refining={false}
      onSelect={onSelect}
      onDetails={onDetails}
    />,
  );
  return { ...result, item, view, onSelect, onDetails };
}

describe('RouteSummaryCard 정보 위계', () => {
  it('소요 시간·추천 근거·상세 CTA를 순서대로 노출하고 선택은 route id를 유지한다', () => {
    const { container, onSelect, onDetails, view } = renderCard('general');

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
    ).toMatch(/최단 시간|보통 경사|도보/);
    expect(view.reasonHighlights.length).toBeGreaterThan(0);
    expect(view.reasonHighlights.length).toBeLessThanOrEqual(3);
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

describe('MOB-15 대중교통 경로 시각 언어', () => {
  it('도보·버스·지하철을 아이콘과 텍스트로 함께 표시한다', () => {
    const { container } = renderCard('general', {
      segments: [
        {
          id: 'walk-start',
          mode: 'walk',
          description: '정류장까지 도보',
          durationMin: 4,
        },
        {
          id: 'bus-81',
          mode: 'bus',
          description: '81번 버스',
          durationMin: 8,
          busRouteName: '81',
        },
        {
          id: 'subway-1',
          mode: 'subway',
          description: '부산 1호선',
          durationMin: 5,
        },
      ],
    });

    const sequence = container.querySelector(
      '.map-first__route-card-transit[aria-label="이동 수단 순서"]',
    )!;
    expect(sequence.querySelectorAll('li')).toHaveLength(3);
    expect(sequence.textContent).toMatch(/도보.*4분/);
    expect(sequence.textContent).toMatch(/버스.*81번.*8분/);
    expect(sequence.textContent).toMatch(/지하철.*1호선.*5분/);
    expect(
      sequence.querySelector('[data-subway-line="busan-1"]'),
    ).toBeTruthy();
    expect(sequence.querySelectorAll('svg[aria-hidden="true"]')).toHaveLength(3);
  });

  it.each([
    'general',
    'youth',
    'elderly',
    'child',
    'disabled',
    'pregnant',
  ] as ProfileId[])(
    '프로필 %s에서도 동일한 이동수단 순서 DOM을 사용한다',
    (profile) => {
      const { container } = renderCard(profile, {
        segments: [
          {
            id: 'walk-start',
            mode: 'walk',
            description: '도보',
            durationMin: 3,
          },
          {
            id: 'bus-81',
            mode: 'bus',
            description: '버스',
            durationMin: 8,
            busRouteName: '81',
          },
        ],
      });
      const sequence = container.querySelector(
        '.map-first__route-card-transit',
      )!;
      expect(sequence.querySelectorAll('li')).toHaveLength(2);
      expect(sequence.textContent).toMatch(/도보.*버스.*81번/);
    },
  );
});

describe('MOB-08 경로 카드 본문 우선 노출', () => {
  it('순위·수단·소요시간이 본문(도보·환승)보다 먼저 렌더링된다', () => {
    const { container } = renderCard('youth');
    const card = container.querySelector('.map-first__route-card')!;
    const header = card.querySelector('.map-first__route-card-header')!;
    const body = card.querySelector('.map-first__route-card-body')!;
    const cta = card.querySelector('.map-first__route-card-cta')!;

    expect(header.querySelector('.map-first__rank-badge')?.textContent).toBe(
      '1순위',
    );
    expect(
      header.querySelector('.map-first__route-card-summary')?.textContent,
    ).toContain('버스 1001');
    expect(
      header.querySelector('.map-first__route-card-duration')?.textContent,
    ).toMatch(/24\s*분/);

    expect(body.querySelector('.map-first__route-stats')?.textContent).toMatch(
      /도보/,
    );
    expect(body.querySelector('.map-first__route-stats')?.textContent).toMatch(
      /환승/,
    );

    expect(
      header.compareDocumentPosition(body) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      body.compareDocumentPosition(cta) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('총 소요시간 60분 이상을 시간·분 문구로 표시한다', () => {
    const { container } = renderCard('general', { totalDurationMin: 69 });
    const duration = container.querySelector(
      '.map-first__route-card-duration',
    );
    expect(duration?.textContent).toBe('1시간 9분');
    expect(
      duration?.getAttribute('aria-label'),
    ).toBe('소요시간 1시간 9분');
  });

  it('상세 화면을 열지 않아도 도보·환승·핵심 특성이 카드에 존재한다', () => {
    const { container } = renderCard('youth');
    const card = container.querySelector('.map-first__route-card')!;
    const body = card.querySelector('.map-first__route-card-body')!;

    expect(body.textContent).toMatch(/380\s*m 도보/);
    expect(body.textContent).toMatch(/1\s*회 환승/);
    expect(
      body.querySelector('.map-first__route-card-reasons, .map-first__badges'),
    ).toBeTruthy();
    expect(
      container.querySelector('[aria-label="선택 경로 상세"]'),
    ).toBeNull();
  });

  it('상세 정보 보기는 하단 보조 액션 클래스를 유지한다', () => {
    const { container, onDetails, onSelect } = renderCard('general');
    const cta = container.querySelector('.map-first__route-card-cta')!;

    expect(cta.classList.contains('map-first__sheet-cta')).toBe(true);
    expect(cta.classList.contains('map-first__route-card-cta')).toBe(true);
    expect(cta.getAttribute('type')).toBe('button');
    expect(getComputedStyle(cta).position).not.toBe('absolute');
    expect(getComputedStyle(cta).position).not.toBe('fixed');

    fireEvent.click(cta);
    expect(onDetails).toHaveBeenCalledTimes(1);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it.each([
    'general',
    'youth',
    'elderly',
    'child',
    'disabled',
    'pregnant',
  ] as ProfileId[])(
    '프로필 %s에서도 동일 정보 위계(header→body→cta)를 사용한다',
    (profile) => {
      const { container } = renderCard(profile);
      const card = container.querySelector('.map-first__route-card')!;
      const children = Array.from(card.children).map(
        (el) => el.className.split(/\s+/)[0],
      );

      expect(children).toEqual([
        'map-first__route-card-header',
        'map-first__route-card-body',
        'map-first__sheet-cta',
      ]);
      expect(
        card.querySelector('.map-first__route-card-header .map-first__rank-badge'),
      ).toBeTruthy();
      expect(
        card.querySelector(
          '.map-first__route-card-header .map-first__route-card-summary',
        ),
      ).toBeTruthy();
      expect(
        card.querySelector(
          '.map-first__route-card-header .map-first__route-card-duration',
        ),
      ).toBeTruthy();
      expect(
        card.querySelector('.map-first__route-card-body .map-first__route-stats'),
      ).toBeTruthy();
      expect(
        card.querySelector('.map-first__route-card-cta')?.textContent,
      ).toContain('상세 정보 보기');
    },
  );

  it('짧은 화면 조건에서도 핵심 정보가 DOM에서 제거되지 않는다', () => {
    const previous = {
      width: window.innerWidth,
      height: window.innerHeight,
    };
    Object.defineProperty(window, 'innerWidth', {
      configurable: true,
      value: 375,
    });
    Object.defineProperty(window, 'innerHeight', {
      configurable: true,
      value: 667,
    });

    try {
      const { container } = renderCard('youth', {
        summary: '버스급행 1000(해운대구청) · 센텀시티환승센터 방면',
      });
      const card = container.querySelector('.map-first__route-card')!;
      expect(card.querySelector('.map-first__rank-badge')?.textContent).toContain(
        '1순위',
      );
      expect(
        card.querySelector('.map-first__route-card-summary')?.textContent,
      ).toContain('버스급행');
      expect(
        card.querySelector('.map-first__route-card-duration')?.textContent,
      ).toMatch(/분/);
      expect(
        card.querySelector('.map-first__route-stats')?.textContent,
      ).toMatch(/도보/);
      expect(
        card.querySelector('.map-first__route-stats')?.textContent,
      ).toMatch(/환승/);
      expect(
        card.querySelector('.map-first__route-card-cta'),
      ).toBeTruthy();
    } finally {
      Object.defineProperty(window, 'innerWidth', {
        configurable: true,
        value: previous.width,
      });
      Object.defineProperty(window, 'innerHeight', {
        configurable: true,
        value: previous.height,
      });
    }
  });

  it('카드 선택과 상세 열기 이벤트가 분리되어 유지된다', () => {
    const { container, onSelect, onDetails } = renderCard('youth');
    const card = container.querySelector('.map-first__route-card')!;

    fireEvent.keyDown(card, { key: 'Enter' });
    expect(onSelect).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: '상세 정보 보기' }));
    expect(onDetails).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledTimes(1);
  });
});
