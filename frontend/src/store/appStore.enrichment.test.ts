import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { adapters } from '@/adapters';
import { findPlace } from '@/data/places';
import { demoCandidates } from '@/data/routes';
import { WEATHER_SCENARIOS } from '@/data/weather';
import { recommendRoutes } from '@/scoring/engine';
import type { TransitRefinement } from '@/types';
import { useAppStore } from './appStore';

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function seedEstimatedTransitResults() {
  const baseline = recommendRoutes(
    demoCandidates(),
    WEATHER_SCENARIOS.normal,
    'general',
  );
  const recommendations = baseline.map((item) => ({
    ...item,
    routeSetToken: 'route-set-token-1234567890',
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
    profile: 'general',
    weatherScenario: 'normal',
    options: {},
    candidates: recommendations.map(({ route }) => route),
    recommendations,
    selectedRouteId: recommendations[0].route.id,
    loading: false,
    error: null,
    refiningRouteKeys: [],
  });
  return recommendations;
}

function transitRouteId(
  recommendations: ReturnType<typeof seedEstimatedTransitResults>,
): string {
  const withTransit = recommendations.find(({ route }) =>
    route.segments.some(
      (segment) => segment.mode === 'bus' || segment.mode === 'subway',
    ),
  );
  expect(withTransit).toBeTruthy();
  return withTransit!.route.id;
}

beforeEach(() => {
  useAppStore.setState({
    candidates: [],
    recommendations: [],
    selectedRouteId: null,
    loading: false,
    error: null,
    refiningRouteKeys: [],
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('카드 선택 시 대중교통 지연 정밀화', () => {
  it('estimated 대중교통 후보 선택은 refinement endpoint만 호출하고 geometry를 patch한다', async () => {
    const recommendations = seedEstimatedTransitResults();
    const routeId = transitRouteId(recommendations);
    const refined: TransitRefinement = {
      routeId,
      path: [
        { lat: 35.1, lng: 129.0 },
        { lat: 35.2, lng: 129.1 },
      ],
      segments: recommendations
        .find(({ route }) => route.id === routeId)!
        .route.segments.map((segment) => ({
          ...segment,
          geometryQuality: 'exact' as const,
        })),
      geometryQuality: 'exact',
    };
    const refineTransit = vi
      .spyOn(adapters.routes, 'refineTransit')
      .mockResolvedValue(refined);
    const recommend = vi.spyOn(adapters.routes, 'recommend');

    useAppStore.getState().selectRoute(routeId);
    await vi.waitFor(() => {
      const updated = useAppStore
        .getState()
        .recommendations.find(({ route }) => route.id === routeId);
      expect(updated?.route.geometryQuality).toBe('exact');
    });

    expect(refineTransit).toHaveBeenCalledTimes(1);
    expect(refineTransit).toHaveBeenCalledWith(
      'route-set-token-1234567890',
      routeId,
    );
    // 전체 재검색·재순위화는 발생하지 않는다.
    expect(recommend).not.toHaveBeenCalled();
    // 순위·카드 순서·다른 후보는 변경되지 않는다.
    expect(
      useAppStore.getState().recommendations.map(({ route }) => route.id),
    ).toEqual(recommendations.map(({ route }) => route.id));
    expect(useAppStore.getState().selectedRouteId).toBe(routeId);
  });

  it('이미 exact인 후보 재선택은 refinement를 호출하지 않는다', async () => {
    const recommendations = seedEstimatedTransitResults();
    const routeId = transitRouteId(recommendations);
    useAppStore.setState({
      recommendations: useAppStore.getState().recommendations.map((item) => ({
        ...item,
        route: {
          ...item.route,
          geometryQuality: 'exact' as const,
          segments: item.route.segments.map((segment) => ({
            ...segment,
            geometryQuality: 'exact' as const,
          })),
        },
      })),
    });
    const refineTransit = vi.spyOn(adapters.routes, 'refineTransit');

    useAppStore.getState().selectRoute(routeId);
    await Promise.resolve();

    expect(refineTransit).not.toHaveBeenCalled();
  });

  it('빠른 카드 전환에서 늦은 응답은 해당 후보 저장분만 갱신하고 현재 선택을 바꾸지 않는다', async () => {
    const recommendations = seedEstimatedTransitResults();
    const withTransit = recommendations.filter(({ route }) =>
      route.segments.some(
        (segment) => segment.mode === 'bus' || segment.mode === 'subway',
      ),
    );
    expect(withTransit.length).toBeGreaterThanOrEqual(2);
    const firstId = withTransit[0].route.id;
    const secondId = withTransit[1].route.id;
    const firstResponse = deferred<TransitRefinement>();
    const refineTransit = vi
      .spyOn(adapters.routes, 'refineTransit')
      .mockImplementation((_token, routeId) => {
        if (routeId === firstId) return firstResponse.promise;
        return Promise.resolve({
          routeId,
          path: [
            { lat: 35.3, lng: 129.2 },
            { lat: 35.4, lng: 129.3 },
          ],
          segments: [],
          geometryQuality: 'exact',
        } as TransitRefinement);
      });

    // 1번 후보의 정밀화가 실제로 시작되도록 debounce가 지난 뒤 전환한다.
    useAppStore.getState().selectRoute(firstId);
    await vi.waitFor(() => {
      expect(refineTransit).toHaveBeenCalledWith(
        expect.any(String),
        firstId,
      );
    });
    useAppStore.getState().selectRoute(secondId);
    expect(useAppStore.getState().selectedRouteId).toBe(secondId);

    // 1번 후보의 늦은 응답이 도착해도 현재 선택은 2번 후보로 유지된다.
    firstResponse.resolve({
      routeId: firstId,
      path: [
        { lat: 35.5, lng: 129.4 },
        { lat: 35.6, lng: 129.5 },
      ],
      segments: [],
      geometryQuality: 'exact',
    });
    await vi.waitFor(() => {
      const first = useAppStore
        .getState()
        .recommendations.find(({ route }) => route.id === firstId);
      expect(first?.route.geometryQuality).toBe('exact');
    });
    expect(useAppStore.getState().selectedRouteId).toBe(secondId);
    // 2번 후보의 정밀화는 debounce가 지난 뒤 시작된다.
    await vi.waitFor(() => {
      expect(refineTransit).toHaveBeenCalledTimes(2);
    });
    expect(refineTransit).toHaveBeenCalledWith(expect.any(String), secondId);
  });

  it('진행 중인 후보를 다시 선택해도 중복 refinement를 만들지 않는다', async () => {
    const recommendations = seedEstimatedTransitResults();
    const routeId = transitRouteId(recommendations);
    const pending = deferred<TransitRefinement>();
    const refineTransit = vi
      .spyOn(adapters.routes, 'refineTransit')
      .mockReturnValue(pending.promise);

    // 선택 상태는 즉시 바뀌지만 외부 호출은 debounce 후 한 번만 나간다.
    useAppStore.getState().selectRoute(routeId);
    useAppStore.getState().selectRoute(routeId);
    await vi.waitFor(() => {
      expect(refineTransit).toHaveBeenCalledTimes(1);
    });
    useAppStore.getState().selectRoute(routeId);
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(refineTransit).toHaveBeenCalledTimes(1);

    pending.resolve({
      routeId,
      path: [
        { lat: 35.1, lng: 129.0 },
        { lat: 35.2, lng: 129.1 },
      ],
      segments: [],
      geometryQuality: 'exact',
    });
    await pending.promise;
  });
});
