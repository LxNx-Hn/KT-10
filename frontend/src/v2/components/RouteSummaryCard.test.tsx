// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ProfileId, ScoredRoute } from '@/types';
import { buildRouteViewModel } from '../routeViewModel';
import RouteSummaryCard, { formatRouteCardTitle } from './RouteSummaryCard';

afterEach(() => {
  cleanup();
});

function makeItem(overrides: Partial<ScoredRoute['route']> = {}): ScoredRoute {
  return {
    route: {
      id: 'route-a',
      summary: '도보 + 1001',
      origin: '출발',
      destination: '도착',
      segments: [
        {
          id: 'w1',
          mode: 'walk',
          description: '도보',
          durationMin: 6,
          hasStairs: false,
          stairsCount: 0,
        },
        {
          id: 'b1',
          mode: 'bus',
          description: '버스',
          durationMin: 18,
          busRouteName: '1001',
        },
      ],
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

describe('formatRouteCardTitle', () => {
  it('도보만 있으면 도보로 표시한다', () => {
    expect(
      formatRouteCardTitle(
        [{ id: 'w', mode: 'walk', modeLabel: '도보', durationMin: 12 }],
        '도보 + 12',
      ),
    ).toBe('도보');
  });

  it('버스·지하철은 routeLabel이 있으면 함께 표시하고 없으면 fallback한다', () => {
    expect(
      formatRouteCardTitle(
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
      formatRouteCardTitle(
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
      formatRouteCardTitle(
        [{ id: 'b', mode: 'bus', modeLabel: '버스', durationMin: 10 }],
        '도보 + 버스',
      ),
    ).toBe('버스');
  });

  it('버스+지하철 복합은 transitSteps 기준으로 연결한다', () => {
    expect(
      formatRouteCardTitle(
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

  it('복수 버스는 순서대로 join한다', () => {
    expect(
      formatRouteCardTitle(
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
        ],
        '도보 + 3006 + 58-2 + 1001(심야)',
      ),
    ).toBe('버스 3006번 · 버스 58-2번 · 버스 1001(심야)번');
  });
});

describe('RouteSummaryCard 정보 위계', () => {
  it('소요 시간·추천 근거·상세 CTA를 순서대로 노출하고 선택은 route id를 유지한다', () => {
    const { container, onSelect, onDetails, view } = renderCard('general');

    const card = container.querySelector('.map-first__route-card');
    expect(card?.getAttribute('data-route-id')).toBe('route-a');
    expect(card?.getAttribute('aria-current')).toBe('true');
    expect(card?.textContent).toContain('1순위');
    expect(
      card?.querySelector('.map-first__route-card-summary')?.textContent,
    ).toBe('버스 1001번');
    expect(card?.textContent).not.toContain('도보 + 1001');
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
  it('도보·버스·지하철을 segmented bar와 아이콘·텍스트로 표시한다', () => {
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
    const items = sequence.querySelectorAll('li');
    expect(items).toHaveLength(3);
    // 도보는 지도 선 색 설명을 함께 읽어준다. 다른 수단은 노선명이 대신한다.
    expect(items[0].getAttribute('aria-label')).toBe('도보 지도에서 회색 선 4분');
    expect(items[1].getAttribute('aria-label')).toBe('버스 81번 8분');
    expect(items[2].getAttribute('aria-label')).toBe('지하철 1호선 5분');
    expect(items[0].textContent).toMatch(/4분/);
    expect(items[1].textContent).toMatch(/8분/);
    expect(items[2].textContent).toMatch(/5분/);
    expect(sequence.textContent).not.toMatch(/81번/);
    expect(sequence.textContent).not.toMatch(/1호선/);
    expect(items[0].getAttribute('style')).toContain('flex-grow: 4');
    expect(items[1].getAttribute('style')).toContain('flex-grow: 8');
    expect(items[2].getAttribute('style')).toContain('flex-grow: 5');
    expect(sequence.querySelector('[data-mode="walk"]')).toBeTruthy();
    expect(
      sequence.querySelector('[data-mode="walk"]')?.getAttribute('aria-label'),
    ).toContain('지도에서 회색 선');
    expect(
      sequence.querySelector('[data-subway-line="busan-1"]'),
    ).toBeTruthy();
    expect(sequence.querySelectorAll('svg[aria-hidden="true"]')).toHaveLength(3);
    expect(
      container.querySelector('.map-first__route-card-summary')?.textContent,
    ).toBe('버스 81번 · 지하철 1호선');
  });

  it('walk + bus + walk 제목은 버스로 요약하고 순서를 유지한다', () => {
    const { container } = renderCard('general', {
      summary: '도보 + 59',
      segments: [
        {
          id: 'w1',
          mode: 'walk',
          description: '도보',
          durationMin: 2,
        },
        {
          id: 'b59',
          mode: 'bus',
          description: '버스',
          durationMin: 56,
          busRouteName: '59',
        },
        {
          id: 'w2',
          mode: 'walk',
          description: '도보',
          durationMin: 5,
        },
      ],
    });

    expect(
      container.querySelector('.map-first__route-card-summary')?.textContent,
    ).toBe('버스 59번');
    const items = container.querySelectorAll('.map-first__route-card-transit li');
    expect(items).toHaveLength(3);
    expect(items[0].getAttribute('data-mode')).toBe('walk');
    expect(items[1].getAttribute('data-mode')).toBe('bus');
    expect(items[2].getAttribute('data-mode')).toBe('walk');
    expect(items[0].textContent).toMatch(/2분/);
    expect(items[1].textContent).toMatch(/56분/);
    expect(items[2].textContent).toMatch(/5분/);
    expect(items[1].textContent).not.toMatch(/59/);
    expect(items[1].getAttribute('aria-label')).toBe('버스 59번 56분');
  });

  it('7 segment 다중 환승에서도 모든 duration·aria를 보존하고 routeLabel은 bar에 없다', () => {
    const { container, view } = renderCard('general', {
      summary: '도보 + 3006 + 58-2 + 1001(심야)',
      segments: [
        { id: 'w1', mode: 'walk', description: '도보', durationMin: 11 },
        {
          id: 'b3006',
          mode: 'bus',
          description: '버스',
          durationMin: 42,
          busRouteName: '3006',
        },
        { id: 'w2', mode: 'walk', description: '도보', durationMin: 4 },
        {
          id: 'b582',
          mode: 'bus',
          description: '버스',
          durationMin: 63,
          busRouteName: '58-2',
        },
        { id: 'w3', mode: 'walk', description: '도보', durationMin: 6 },
        {
          id: 'b1001n',
          mode: 'bus',
          description: '버스',
          durationMin: 67,
          busRouteName: '1001(심야)',
        },
        { id: 'w4', mode: 'walk', description: '도보', durationMin: 5 },
      ],
      totalDurationMin: 198,
      transferCount: 2,
    });

    const title = formatRouteCardTitle(view.transitSteps, view.summary);
    expect(title).toBe('버스 3006번 · 버스 58-2번 · 버스 1001(심야)번');
    expect(
      container.querySelector('.map-first__route-card-summary')?.textContent,
    ).toBe(title);

    const sequence = container.querySelector(
      '.map-first__route-card-transit',
    )!;
    expect(sequence.getAttribute('data-compact')).toBe('true');
    const items = sequence.querySelectorAll('li');
    expect(items).toHaveLength(7);

    const text = sequence.textContent ?? '';
    expect(text).toMatch(/11분/);
    expect(text).toMatch(/42분/);
    expect(text).toMatch(/4분/);
    expect(text).toMatch(/63분/);
    expect(text).toMatch(/6분/);
    expect(text).toMatch(/67분/);
    expect(text).toMatch(/5분/);
    expect(text).not.toContain('3006');
    expect(text).not.toContain('58-2');
    expect(text).not.toContain('1001');
    expect(text).not.toMatch(/버스/);
    expect(text).not.toMatch(/도보/);

    expect(items[0].querySelector('.map-first__transit-copy')?.textContent).toBe(
      '11분',
    );
    expect(items[2].querySelector('.map-first__transit-copy')?.textContent).toBe(
      '4분',
    );
    expect(items[4].querySelector('.map-first__transit-copy')?.textContent).toBe(
      '6분',
    );
    expect(items[6].querySelector('.map-first__transit-copy')?.textContent).toBe(
      '5분',
    );

    expect(items[1].getAttribute('aria-label')).toBe('버스 3006번 42분');
    expect(items[3].getAttribute('aria-label')).toBe('버스 58-2번 63분');
    expect(items[5].getAttribute('aria-label')).toBe('버스 1001(심야)번 67분');
    expect(items[0].getAttribute('aria-label')).toBe('도보 지도에서 회색 선 11분');
  });

  it('walk + subway + bus 복합에서도 각 segment 시간만 bar에 표시한다', () => {
    const { container } = renderCard('general', {
      summary: '도보 + 복합',
      segments: [
        { id: 'w1', mode: 'walk', description: '도보', durationMin: 4 },
        {
          id: 's1',
          mode: 'subway',
          description: '부산 2호선',
          durationMin: 22,
        },
        { id: 'w2', mode: 'walk', description: '도보', durationMin: 2 },
        {
          id: 'b139',
          mode: 'bus',
          description: '버스',
          durationMin: 18,
          busRouteName: '139',
        },
        { id: 'w3', mode: 'walk', description: '도보', durationMin: 3 },
      ],
    });

    expect(
      container.querySelector('.map-first__route-card-summary')?.textContent,
    ).toBe('지하철 2호선 · 버스 139번');

    const items = container.querySelectorAll('.map-first__route-card-transit li');
    expect(items).toHaveLength(5);
    expect(Array.from(items).map((el) => el.querySelector('.map-first__transit-copy')?.textContent)).toEqual([
      '4분',
      '22분',
      '2분',
      '18분',
      '3분',
    ]);
    expect(container.querySelector('.map-first__route-card-transit')?.textContent).not.toMatch(
      /2호선|139/,
    );
    expect(items[1].getAttribute('aria-label')).toBe('지하철 2호선 22분');
    expect(items[3].getAttribute('aria-label')).toBe('버스 139번 18분');
    expect(items[1].getAttribute('data-subway-line')).toBe('busan-2');
  });

  it('walk + subway 제목과 walk only / bus label 없음을 처리한다', () => {
    const subway = renderCard('general', {
      summary: '도보 + 1',
      segments: [
        { id: 'w1', mode: 'walk', description: '도보', durationMin: 3 },
        {
          id: 's1',
          mode: 'subway',
          description: '부산 2호선',
          durationMin: 18,
        },
        { id: 'w2', mode: 'walk', description: '도보', durationMin: 2 },
      ],
    });
    expect(
      subway.container.querySelector('.map-first__route-card-summary')
        ?.textContent,
    ).toBe('지하철 2호선');
    subway.unmount();

    const walkOnly = renderCard('general', {
      summary: '도보 12분',
      segments: [
        { id: 'w1', mode: 'walk', description: '도보', durationMin: 12 },
      ],
    });
    expect(
      walkOnly.container.querySelector('.map-first__route-card-summary')
        ?.textContent,
    ).toBe('도보');
    walkOnly.unmount();

    const busNoLabel = renderCard('general', {
      summary: '도보 + 버스',
      segments: [
        { id: 'w1', mode: 'walk', description: '도보', durationMin: 2 },
        {
          id: 'b1',
          mode: 'bus',
          description: '버스',
          durationMin: 20,
        },
      ],
    });
    expect(
      busNoLabel.container.querySelector('.map-first__route-card-summary')
        ?.textContent,
    ).toBe('버스');
    expect(
      busNoLabel.container
        .querySelector('.map-first__route-card-transit li[data-mode="bus"]')
        ?.getAttribute('aria-label'),
    ).toBe('버스 20분');
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
      expect(sequence.textContent).toMatch(/3분/);
      expect(sequence.textContent).toMatch(/8분/);
      expect(sequence.textContent).not.toMatch(/81번/);
    },
  );

  it('대중교통 사이 0분 도보는 환승으로 표시한다', () => {
    const { container } = renderCard('general', {
      segments: [
        { id: 'w1', mode: 'walk', description: '도보', durationMin: 2 },
        {
          id: 'b1',
          mode: 'bus',
          description: '버스',
          durationMin: 4,
          busRouteName: '49',
        },
        { id: 'w0', mode: 'walk', description: '도보', durationMin: 0 },
        {
          id: 'b2',
          mode: 'bus',
          description: '버스',
          durationMin: 19,
          busRouteName: '77',
        },
        { id: 'w2', mode: 'walk', description: '도보', durationMin: 4 },
      ],
    });

    const items = container.querySelectorAll(
      '.map-first__route-card-transit li',
    );
    expect(items).toHaveLength(5);
    expect(
      Array.from(items).map((el) => ({
        mode: el.getAttribute('data-mode'),
        label: el.querySelector('.map-first__transit-copy')?.textContent,
      })),
    ).toEqual([
      { mode: 'walk', label: '2분' },
      { mode: 'bus', label: '4분' },
      { mode: 'transfer', label: '환승' },
      { mode: 'bus', label: '19분' },
      { mode: 'walk', label: '4분' },
    ]);
    expect(items[2].getAttribute('aria-label')).toBe('환승');
    expect(
      container.querySelector('.map-first__route-card-transit')?.textContent,
    ).not.toContain('0분');
  });

  it('시작·끝 0분 도보는 이동 수단 막대에서 숨긴다', () => {
    const { container } = renderCard('general', {
      segments: [
        { id: 'w-start', mode: 'walk', description: '도보', durationMin: 0 },
        {
          id: 'b1',
          mode: 'bus',
          description: '버스',
          durationMin: 12,
          busRouteName: '49',
        },
        { id: 'w-end', mode: 'walk', description: '도보', durationMin: 0 },
      ],
    });

    const items = container.querySelectorAll(
      '.map-first__route-card-transit li',
    );
    expect(items).toHaveLength(1);
    expect(items[0].getAttribute('data-mode')).toBe('bus');
    expect(items[0].querySelector('.map-first__transit-copy')?.textContent).toBe(
      '12분',
    );
    expect(
      Array.from(items).some((el) => el.getAttribute('data-mode') === 'walk'),
    ).toBe(false);
    expect(
      Array.from(items).some(
        (el) => el.getAttribute('data-mode') === 'transfer',
      ),
    ).toBe(false);
    expect(
      container.querySelector('.map-first__route-card-transit')?.textContent,
    ).not.toContain('0분');
  });
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
    ).toBe('버스 1001번');
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
      value: 353,
    });
    Object.defineProperty(window, 'innerHeight', {
      configurable: true,
      value: 850,
    });

    try {
      const { container } = renderCard('youth', {
        summary: '도보 + 1000',
        segments: [
          { id: 'w1', mode: 'walk', description: '도보', durationMin: 5 },
          {
            id: 'b1',
            mode: 'bus',
            description: '버스',
            durationMin: 40,
            busRouteName: '1000',
          },
        ],
      });
      const card = container.querySelector('.map-first__route-card')!;
      expect(card.querySelector('.map-first__rank-badge')?.textContent).toContain(
        '1순위',
      );
      expect(
        card.querySelector('.map-first__route-card-summary')?.textContent,
      ).toBe('버스 1000번');
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
      expect(
        card.querySelectorAll('.map-first__route-card-transit li').length,
      ).toBe(2);
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
