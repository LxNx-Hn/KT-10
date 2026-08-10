// @vitest-environment jsdom
/**
 * PR #18 코드 검토에서 확인된 카드 상호작용·접근성 문제의 재현 테스트.
 * 각 테스트는 수정 전 실패하고 수정 후 통과해야 한다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render } from '@testing-library/react';
import App from '@/App';
import { adapters } from '@/adapters';
import { MOBILE_STARTUP_STORAGE_KEY } from '@/components/MobileStartupScreen';
import { findPlace } from '@/data/places';
import { demoCandidates } from '@/data/routes';
import { WEATHER_SCENARIOS } from '@/data/weather';
import { recommendRoutes } from '@/scoring/engine';
import { useAppStore } from '@/store/appStore';
import type { ScoredRoute, TransitRefinement } from '@/types';

vi.mock('@/v2/KakaoMap', async () => ({
  ...(await vi.importActual<object>('@/v2/KakaoMap')),
  default: () => (
    <section role="region" aria-label="지도" className="map-first__map" />
  ),
}));

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

const ROUTE_SET_TOKEN = 'token-ui-pr18-0000000000000';

function seedEstimatedResults(): ScoredRoute[] {
  const baseline = recommendRoutes(
    demoCandidates(),
    WEATHER_SCENARIOS.normal,
    'general',
  );
  const recommendations = baseline.map((item) => ({
    ...item,
    routeSetToken: ROUTE_SET_TOKEN,
    route: {
      ...item.route,
      geometryQuality: 'mixed' as const,
      segments: item.route.segments.map((segment) => (
        segment.mode === 'bus' || segment.mode === 'subway'
          ? { ...segment, geometryQuality: 'estimated' as const }
          : segment
      )),
    },
  }));
  useAppStore.setState({
    origin: findPlace('gu-office') ?? null,
    destination: findPlace('seomyeon-stn') ?? null,
    candidates: recommendations.map(({ route }) => route),
    recommendations,
    selectedRouteId: recommendations[0]?.route.id ?? null,
    loading: false,
    error: null,
    refiningRouteKeys: [],
  });
  return recommendations;
}

function cardFor(container: HTMLElement, routeId: string): HTMLElement {
  const card = container.querySelector<HTMLElement>(
    `[data-route-id="${routeId}"]`,
  );
  expect(card).toBeTruthy();
  return card!;
}

beforeEach(() => {
  window.localStorage.setItem(MOBILE_STARTUP_STORAGE_KEY, '1');
  useAppStore.setState({
    profile: 'general',
    origin: null,
    destination: null,
    candidates: [],
    recommendations: [],
    selectedRouteId: null,
    options: {},
    largeUi: false,
    loading: false,
    error: null,
    refiningRouteKeys: [],
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('PR #18 재현 — focus만으로 refinement 호출', () => {
  it('Tab focus 이동은 loadLane refinement를 유발하지 않아야 한다', async () => {
    const refine = vi
      .spyOn(adapters.routes, 'refineTransit')
      .mockResolvedValue(null);
    const { container } = render(<App />);
    act(() => {
      seedEstimatedResults();
    });
    const results = useAppStore.getState().recommendations;
    const target = results[1].route.id;

    refine.mockClear();
    fireEvent.focus(cardFor(container, target));
    await new Promise((resolve) => setTimeout(resolve, 400));

    expect(refine).not.toHaveBeenCalled();
  });
});

describe('PR #18 재현 — refinement 진행 상태가 접근성 tree에 없음', () => {
  it('refinement 중 선택 카드에 aria-busy가 노출되어야 한다', async () => {
    const pending = deferred<TransitRefinement | null>();
    vi.spyOn(adapters.routes, 'refineTransit').mockReturnValue(
      pending.promise,
    );
    const { container } = render(<App />);
    act(() => {
      seedEstimatedResults();
    });
    const results = useAppStore.getState().recommendations;
    const target = results[1].route.id;

    await act(async () => {
      fireEvent.click(cardFor(container, target));
      await new Promise((resolve) => setTimeout(resolve, 300));
    });

    const card = cardFor(container, target);
    expect(card.getAttribute('aria-busy')).toBe('true');

    await act(async () => {
      pending.resolve(null);
      await new Promise((resolve) => setTimeout(resolve, 50));
    });

    expect(cardFor(container, target).getAttribute('aria-busy')).toBeNull();
  });

  it('refinement 중이 아닌 다른 카드는 busy 상태가 아니다', async () => {
    const pending = deferred<TransitRefinement | null>();
    vi.spyOn(adapters.routes, 'refineTransit').mockReturnValue(
      pending.promise,
    );
    const { container } = render(<App />);
    act(() => {
      seedEstimatedResults();
    });
    const results = useAppStore.getState().recommendations;

    await act(async () => {
      fireEvent.click(cardFor(container, results[1].route.id));
      await new Promise((resolve) => setTimeout(resolve, 300));
    });

    expect(
      cardFor(container, results[2].route.id).getAttribute('aria-busy'),
    ).toBeNull();

    await act(async () => {
      pending.resolve(null);
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
  });

  it('refinement 실패 시에도 aria-busy가 제거되어야 한다', async () => {
    vi.spyOn(adapters.routes, 'refineTransit').mockRejectedValue(
      new Error('timeout'),
    );
    const { container } = render(<App />);
    act(() => {
      seedEstimatedResults();
    });
    const target = useAppStore.getState().recommendations[1].route.id;

    await act(async () => {
      fireEvent.click(cardFor(container, target));
      await new Promise((resolve) => setTimeout(resolve, 300));
    });

    expect(cardFor(container, target).getAttribute('aria-busy')).toBeNull();
  });

  it('component unmount 뒤 도착한 응답은 store를 patch하지 않아야 한다', async () => {
    const pending = deferred<TransitRefinement | null>();
    vi.spyOn(adapters.routes, 'refineTransit').mockReturnValue(
      pending.promise,
    );
    const rendered = render(<App />);
    act(() => {
      seedEstimatedResults();
    });
    const target = useAppStore.getState().recommendations[1];

    await act(async () => {
      fireEvent.click(cardFor(rendered.container, target.route.id));
      await new Promise((resolve) => setTimeout(resolve, 300));
    });
    rendered.unmount();

    pending.resolve({
      routeId: target.route.id,
      path: [
        { lat: 35.0, lng: 129.0 },
        { lat: 35.1, lng: 129.1 },
      ],
      segments: target.route.segments,
      geometryQuality: 'exact',
    });
    await pending.promise;
    await Promise.resolve();

    const stored = useAppStore.getState().recommendations.find(
      ({ route }) => route.id === target.route.id,
    );
    expect(stored?.route.geometryQuality).toBe('mixed');
  });
});
