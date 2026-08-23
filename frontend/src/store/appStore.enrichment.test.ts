import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { adapters } from '@/adapters';
import { findPlace } from '@/data/places';
import { demoCandidates } from '@/data/routes';
import { WEATHER_SCENARIOS } from '@/data/weather';
import { recommendRoutes } from '@/scoring/engine';
import type { TransitRefinement, ScoredRoute } from '@/types';
import { serverRankedRecommendations } from '@/utils/routes';
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
    const recommendations = withTransitFirst(seedEstimatedTransitResults());
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
    const recommendations = withTransitFirst(seedEstimatedTransitResults());
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
    const recommendations = withTransitFirst(seedEstimatedTransitResults());
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
    const recommendations = withTransitFirst(seedEstimatedTransitResults());
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

function withTransitFirst(
  recommendations: ReturnType<typeof seedEstimatedTransitResults>,
) {
  const transitIdx = recommendations.findIndex(({ route }) =>
    route.segments.some(
      (segment) => segment.mode === 'bus' || segment.mode === 'subway',
    ),
  );
  if (transitIdx <= 0) return recommendations;
  return [
    recommendations[transitIdx],
    ...recommendations.filter((_, index) => index !== transitIdx),
  ];
}

describe('검색 직후 1순위 자동 선택의 대중교통 정밀화', () => {
  function withUnavailablePublicShade(
    recommendations: ScoredRoute[],
  ): ScoredRoute[] {
    return recommendations.map((item) => ({
      ...item,
      route: {
        ...item.route,
        shade: {
          status: 'unavailable' as const,
          evaluatedAt: '2026-08-22T14:00:00+09:00',
          source: 'VWorld LT_C_BLDGINFO WFS',
          dataQuality: 'public' as const,
          shadowPolygons: [],
          pathSegments: [],
          calculationNote: '건물 회랑을 준비 중입니다.',
        },
      },
    }));
  }

  async function searchWith(
    recommendations: ScoredRoute[],
  ) {
    vi.spyOn(adapters.routes, 'recommend').mockResolvedValue(recommendations);
    vi.spyOn(adapters.weather, 'getCurrent').mockResolvedValue(
      WEATHER_SCENARIOS.normal,
    );
    useAppStore.setState({
      origin: findPlace('gu-office') ?? null,
      destination: findPlace('seomyeon-stn') ?? null,
      candidates: [],
      recommendations: [],
      selectedRouteId: null,
      loading: false,
      error: null,
      refiningRouteKeys: [],
    });
    await useAppStore.getState().search();
  }

  it('검색 후 1순위 estimated transit는 refineTransit을 1회 호출한다', async () => {
    const recommendations = withTransitFirst(seedEstimatedTransitResults());
    const firstId = recommendations[0].route.id;
    const refined: TransitRefinement = {
      routeId: firstId,
      path: [
        { lat: 35.11, lng: 129.01 },
        { lat: 35.21, lng: 129.11 },
      ],
      segments: recommendations[0].route.segments.map((segment) => ({
        ...segment,
        geometryQuality: 'exact' as const,
      })),
      geometryQuality: 'exact',
    };
    const refineTransit = vi
      .spyOn(adapters.routes, 'refineTransit')
      .mockResolvedValue(refined);

    await searchWith(recommendations);
    expect(useAppStore.getState().selectedRouteId).toBe(firstId);
    await vi.waitFor(() => {
      expect(refineTransit).toHaveBeenCalledTimes(1);
    });
    expect(refineTransit).toHaveBeenCalledWith(
      'route-set-token-1234567890',
      firstId,
    );
    await vi.waitFor(() => {
      expect(
        useAppStore.getState().recommendations[0]?.route.geometryQuality,
      ).toBe('exact');
    });
    expect(
      useAppStore.getState().recommendations[0]?.route.path,
    ).toEqual(refined.path);
    expect(adapters.routes.recommend).toHaveBeenCalledTimes(1);
  });

  it('VWorld 회랑이 준비 중이면 경로를 먼저 표시하고 그늘을 자동 갱신한다', async () => {
    const recommendations = withUnavailablePublicShade(
      withTransitFirst(seedEstimatedTransitResults()),
    ).map((item) => ({
      ...item,
      route: {
        ...item.route,
        geometryQuality: 'exact' as const,
        segments: item.route.segments.map((segment) => ({
          ...segment,
          geometryQuality: 'exact' as const,
        })),
      },
    }));
    const refreshed = recommendations.map((item) => ({
      ...item,
      route: {
        ...item.route,
        shade: {
          ...item.route.shade!,
          status: 'estimated_public' as const,
          shadeRatio: 0.42,
          shadedWalkM: 420,
          calculationNote: '확인된 건물 높이 기준 최소 그늘입니다.',
        },
      },
    }));
    const refreshShade = vi
      .spyOn(adapters.routes, 'refreshShade')
      .mockResolvedValue(refreshed);

    await searchWith(recommendations);

    expect(useAppStore.getState().recommendations).toHaveLength(
      recommendations.length,
    );
    await vi.waitFor(() => {
      expect(refreshShade).toHaveBeenCalledTimes(1);
      expect(
        useAppStore.getState().recommendations[0]?.route.shade?.status,
      ).toBe('estimated_public');
    });
    expect(useAppStore.getState().error).toBeNull();
  });

  it('자동 그늘 갱신 실패는 이미 표시한 경로를 오류 화면으로 바꾸지 않는다', async () => {
    const recommendations = withUnavailablePublicShade(
      withTransitFirst(seedEstimatedTransitResults()),
    ).map((item) => ({
      ...item,
      route: {
        ...item.route,
        geometryQuality: 'exact' as const,
        segments: item.route.segments.map((segment) => ({
          ...segment,
          geometryQuality: 'exact' as const,
        })),
      },
    }));
    const refreshShade = vi
      .spyOn(adapters.routes, 'refreshShade')
      .mockRejectedValue(new Error('VWorld timeout'));

    await searchWith(recommendations);
    await vi.waitFor(() => {
      expect(refreshShade).toHaveBeenCalledTimes(1);
    });

    expect(useAppStore.getState().recommendations).toHaveLength(
      recommendations.length,
    );
    expect(useAppStore.getState().error).toBeNull();
  });

  it('늦은 자동 그늘 응답은 먼저 끝난 정밀 선형을 되돌리지 않는다', async () => {
    const recommendations = withUnavailablePublicShade(
      withTransitFirst(seedEstimatedTransitResults()),
    );
    const firstId = recommendations[0].route.id;
    const shadeRefresh = deferred<ScoredRoute[]>();
    vi.spyOn(adapters.routes, 'refreshShade').mockReturnValue(
      shadeRefresh.promise,
    );
    vi.spyOn(adapters.routes, 'refineTransit').mockResolvedValue({
      routeId: firstId,
      path: [
        { lat: 35.11, lng: 129.01 },
        { lat: 35.21, lng: 129.11 },
      ],
      segments: recommendations[0].route.segments.map((segment) => ({
        ...segment,
        geometryQuality: 'exact' as const,
      })),
      geometryQuality: 'exact',
    });

    await searchWith(recommendations);
    await vi.waitFor(() => {
      expect(
        useAppStore.getState().recommendations[0]?.route.geometryQuality,
      ).toBe('exact');
    });

    shadeRefresh.resolve(recommendations.map((item) => ({
      ...item,
      route: {
        ...item.route,
        shade: {
          ...item.route.shade!,
          status: 'estimated_public' as const,
          shadeRatio: 0.37,
          shadedWalkM: 370,
        },
      },
    })));

    await vi.waitFor(() => {
      const route = useAppStore.getState().recommendations[0]?.route;
      expect(route?.shade?.status).toBe('estimated_public');
      expect(route?.geometryQuality).toBe('exact');
    });
  });

  it('exact transit 1순위는 refinement를 호출하지 않는다', async () => {
    const recommendations = withTransitFirst(seedEstimatedTransitResults()).map((item) => ({
      ...item,
      route: {
        ...item.route,
        geometryQuality: 'exact' as const,
        segments: item.route.segments.map((segment) => ({
          ...segment,
          geometryQuality: 'exact' as const,
        })),
      },
    }));
    const refineTransit = vi.spyOn(adapters.routes, 'refineTransit');
    await searchWith(recommendations);
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(refineTransit).not.toHaveBeenCalled();
  });

  it('routeSetToken이 없으면 refinement를 호출하지 않는다', async () => {
    const recommendations = withTransitFirst(seedEstimatedTransitResults()).map((item) => ({
      ...item,
      routeSetToken: undefined,
    }));
    const refineTransit = vi.spyOn(adapters.routes, 'refineTransit');
    await searchWith(recommendations);
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(refineTransit).not.toHaveBeenCalled();
  });

  it('200ms 전에 다른 경로를 선택하면 최초 1순위 refinement를 시작하지 않는다', async () => {
    const recommendations = withTransitFirst(seedEstimatedTransitResults());
    const withTransit = recommendations.filter(({ route }) =>
      route.segments.some(
        (segment) => segment.mode === 'bus' || segment.mode === 'subway',
      ),
    );
    expect(withTransit.length).toBeGreaterThanOrEqual(2);
    const firstId = recommendations[0].route.id;
    const secondId = withTransit.find(({ route }) => route.id !== firstId)!.route.id;
    const refineTransit = vi
      .spyOn(adapters.routes, 'refineTransit')
      .mockResolvedValue({
        routeId: secondId,
        path: [
          { lat: 35.3, lng: 129.2 },
          { lat: 35.4, lng: 129.3 },
        ],
        segments: [],
        geometryQuality: 'exact',
      });

    await searchWith(recommendations);
    useAppStore.getState().selectRoute(secondId);
    await vi.waitFor(() => {
      expect(refineTransit).toHaveBeenCalled();
    });
    expect(refineTransit).toHaveBeenCalledWith(
      'route-set-token-1234567890',
      secondId,
    );
    expect(refineTransit).not.toHaveBeenCalledWith(
      expect.any(String),
      firstId,
    );
    expect(useAppStore.getState().selectedRouteId).toBe(secondId);
  });

  it('refinement 실패 시 원본 geometry와 순위를 유지한다', async () => {
    const recommendations = withTransitFirst(seedEstimatedTransitResults());
    const firstId = recommendations[0].route.id;
    const originalPath = recommendations[0].route.path;
    const refineTransit = vi
      .spyOn(adapters.routes, 'refineTransit')
      .mockRejectedValue(new Error('provider down'));

    await searchWith(recommendations);
    await vi.waitFor(() => {
      expect(refineTransit).toHaveBeenCalledTimes(1);
    });
    await new Promise((resolve) => setTimeout(resolve, 20));
    const state = useAppStore.getState();
    expect(state.selectedRouteId).toBe(firstId);
    expect(state.recommendations.map(({ route }) => route.id)).toEqual(
      recommendations.map(({ route }) => route.id),
    );
    expect(state.recommendations[0]?.route.path).toEqual(originalPath);
    expect(state.recommendations[0]?.route.geometryQuality).toBe('mixed');
    expect(adapters.routes.recommend).toHaveBeenCalledTimes(1);
  });

  it('estimated transit 후보가 5개여도 검색 직후 선택된 1개만 refineTransit한다', async () => {
    const template = withTransitFirst(seedEstimatedTransitResults())[0];
    const recommendations = Array.from({ length: 5 }, (_, index) => ({
      ...template,
      route: {
        ...template.route,
        id: `est-transit-${index}`,
        segments: template.route.segments.map((segment) => ({
          ...segment,
          id: `${segment.id}-${index}`,
          geometryQuality:
            segment.mode === 'bus' || segment.mode === 'subway'
              ? 'estimated' as const
              : segment.geometryQuality,
        })),
      },
    }));
    const firstId = serverRankedRecommendations(recommendations)[0]?.route.id;
    const refineTransit = vi
      .spyOn(adapters.routes, 'refineTransit')
      .mockResolvedValue(null);

    await searchWith(recommendations);
    await vi.waitFor(() => {
      expect(refineTransit).toHaveBeenCalledTimes(1);
    });
    expect(refineTransit).toHaveBeenCalledWith(
      'route-set-token-1234567890',
      firstId,
    );
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(refineTransit).toHaveBeenCalledTimes(1);
    expect(refineTransit.mock.calls.every(([, routeId]) => routeId === firstId)).toBe(true);
    expect(useAppStore.getState().selectedRouteId).toBe(firstId);
  });

  it('검색 후 MapFirstApp 자동선택 effect는 같은 1순위에 selectRoute를 다시 호출하지 않는다', async () => {
    const recommendations = withTransitFirst(seedEstimatedTransitResults());
    const refineTransit = vi
      .spyOn(adapters.routes, 'refineTransit')
      .mockResolvedValue(null);
    const selectRoute = vi.spyOn(useAppStore.getState(), 'selectRoute');

    await searchWith(recommendations);
    expect(selectRoute).toHaveBeenCalledTimes(1);

    const { selectedRouteId, recommendations: recs } = useAppStore.getState();
    const ranked = serverRankedRecommendations(recs);
    if (
      ranked.length > 0
      && !ranked.some(({ route }) => route.id === selectedRouteId)
    ) {
      useAppStore.getState().selectRoute(ranked[0].route.id);
    }

    await vi.waitFor(() => {
      expect(refineTransit).toHaveBeenCalledTimes(1);
    });
    expect(selectRoute).toHaveBeenCalledTimes(1);
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(refineTransit).toHaveBeenCalledTimes(1);
  });
});
