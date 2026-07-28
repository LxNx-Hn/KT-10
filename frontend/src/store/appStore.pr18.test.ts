import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { adapters } from '@/adapters';
import { findPlace } from '@/data/places';
import { demoCandidates } from '@/data/routes';
import { WEATHER_SCENARIOS } from '@/data/weather';
import { recommendRoutes } from '@/scoring/engine';
import type { ScoredRoute, TransitRefinement } from '@/types';
import { routeRefinementKey, useAppStore } from './appStore';

/**
 * PR #18 코드 검토에서 확인된 Frontend 상태 문제의 재현 테스트.
 * 각 테스트는 수정 전 실패하고 수정 후 통과해야 한다.
 */

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function seedResults(routeSetToken: string): ScoredRoute[] {
  const baseline = recommendRoutes(
    demoCandidates(),
    WEATHER_SCENARIOS.normal,
    'general',
  );
  const recommendations = baseline.map((item) => ({
    ...item,
    routeSetToken,
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
    selectedRouteId: null,
    loading: false,
    error: null,
    refiningRouteKeys: [],
  });
  return recommendations;
}

beforeEach(() => {
  useAppStore.setState({
    profile: 'general',
    origin: null,
    destination: null,
    candidates: [],
    recommendations: [],
    selectedRouteId: null,
    options: {},
    loading: false,
    error: null,
    refiningRouteKeys: [],
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('PR #18 재현 — profile·option 변경이 전체 재검색을 유발', () => {
  it('profile 변경은 /recommend 대신 route-set rescore를 사용해야 한다', async () => {
    seedResults('token-aaaaaaaaaaaaaaaaaaaaaaaa');
    const recommend = vi.spyOn(adapters.routes, 'recommend');
    const rescore = vi.spyOn(
      adapters.routes as unknown as { rescore: () => Promise<ScoredRoute[]> },
      'rescore',
    );

    useAppStore.getState().setProfile('elderly');
    await vi.waitFor(() => {
      expect(useAppStore.getState().loading).toBe(false);
    });

    expect(recommend).not.toHaveBeenCalled();
    expect(rescore).toHaveBeenCalledTimes(1);
  });

  it('scoring option 변경도 route-set rescore를 사용해야 한다', async () => {
    seedResults('token-bbbbbbbbbbbbbbbbbbbbbbbb');
    const recommend = vi.spyOn(adapters.routes, 'recommend');

    useAppStore.getState().setScoringOption('avoidStairs', true);
    await vi.waitFor(() => {
      expect(useAppStore.getState().loading).toBe(false);
    });

    expect(recommend).not.toHaveBeenCalled();
  });
});

describe('PR #18 재현 — 이전 검색의 refinement 응답이 새 검색을 덮음', () => {
  it('검색 A 응답이 검색 B의 같은 route ID geometry를 덮지 않아야 한다', async () => {
    const first = seedResults('token-search-A-000000000000');
    const targetId = first[1].route.id;

    const pending = deferred<TransitRefinement | null>();
    vi.spyOn(adapters.routes, 'refineTransit').mockReturnValue(
      pending.promise,
    );

    useAppStore.getState().selectRoute(targetId);

    // 새 검색(B)이 같은 semantic route ID를 포함한 채 도착
    const second = seedResults('token-search-B-000000000000');
    const expectedSegments = second.find(
      ({ route }) => route.id === targetId,
    )!.route.segments;

    // 검색 A에서 시작된 응답이 뒤늦게 도착
    pending.resolve({
      routeId: targetId,
      path: [
        { lat: 35.0, lng: 129.0 },
        { lat: 35.1, lng: 129.1 },
      ],
      segments: expectedSegments.map((segment) => ({
        ...segment,
        geometryQuality: 'exact' as const,
      })),
      geometryQuality: 'exact',
    });
    await pending.promise.catch(() => undefined);
    await Promise.resolve();
    await Promise.resolve();

    const patched = useAppStore
      .getState()
      .recommendations.find(({ route }) => route.id === targetId);

    expect(patched?.route.geometryQuality).toBe('mixed');
    expect(patched?.route.path).toEqual(
      second.find(({ route }) => route.id === targetId)!.route.path,
    );
  });

  it('응답 route ID가 요청 route ID와 다르면 patch하지 않아야 한다', async () => {
    const results = seedResults('token-route-id-check-000000');
    const target = results[1];
    const pending = deferred<TransitRefinement | null>();
    vi.spyOn(adapters.routes, 'refineTransit').mockReturnValue(
      pending.promise,
    );

    useAppStore.getState().selectRoute(target.route.id);
    await new Promise((resolve) => setTimeout(resolve, 250));
    pending.resolve({
      routeId: 'tampered-route-id',
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

  it('새 검색이 debounce 중 시작되면 이전 refinement를 시작하지 않는다', async () => {
    const results = seedResults('token-debounce-search-00000');
    const refine = vi
      .spyOn(adapters.routes, 'refineTransit')
      .mockResolvedValue(null);
    vi.spyOn(adapters.routes, 'recommend').mockResolvedValue(results);
    vi.spyOn(adapters.weather, 'getCurrent').mockResolvedValue(
      WEATHER_SCENARIOS.normal,
    );

    useAppStore.getState().selectRoute(results[1].route.id);
    const search = useAppStore.getState().search();
    await search;
    await new Promise((resolve) => setTimeout(resolve, 300));

    expect(refine).not.toHaveBeenCalled();
  });

  it('검색 오류 뒤 도착한 이전 refinement는 현재 store를 patch하지 않는다', async () => {
    const results = seedResults('token-search-error-00000000');
    const target = results[1];
    const pending = deferred<TransitRefinement | null>();
    vi.spyOn(adapters.routes, 'refineTransit').mockReturnValue(
      pending.promise,
    );
    vi.spyOn(adapters.routes, 'recommend').mockRejectedValue(
      new Error('search failed'),
    );
    vi.spyOn(adapters.weather, 'getCurrent').mockResolvedValue(
      WEATHER_SCENARIOS.normal,
    );

    useAppStore.getState().selectRoute(target.route.id);
    await new Promise((resolve) => setTimeout(resolve, 250));
    await useAppStore.getState().search();
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

  it('이전 route-set 완료가 새 route-set의 동일 route busy를 지우지 않는다', async () => {
    const first = seedResults('token-busy-search-A-000000');
    const targetId = first[1].route.id;
    const oldRequest = deferred<TransitRefinement | null>();
    const newRequest = deferred<TransitRefinement | null>();
    vi.spyOn(adapters.routes, 'refineTransit')
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(newRequest.promise);

    useAppStore.getState().selectRoute(targetId);
    await new Promise((resolve) => setTimeout(resolve, 250));
    const second = seedResults('token-busy-search-B-000000');
    useAppStore.getState().selectRoute(targetId);
    await new Promise((resolve) => setTimeout(resolve, 250));

    const newKey = routeRefinementKey(
      second[1].routeSetToken!,
      targetId,
    );
    expect(useAppStore.getState().refiningRouteKeys).toContain(newKey);

    oldRequest.resolve(null);
    await oldRequest.promise;
    await Promise.resolve();

    expect(useAppStore.getState().refiningRouteKeys).toContain(newKey);
    newRequest.resolve(null);
    await newRequest.promise;
  });
});

describe('PR #18 재현 — 빠른 카드 이동이 여러 refinement를 유발', () => {
  it('2→3→4 빠른 이동에서 마지막 후보만 refinement해야 한다', async () => {
    const seeded = seedResults('token-cccccccccccccccccccccccc');
    const refine = vi
      .spyOn(adapters.routes, 'refineTransit')
      .mockResolvedValue(null);

    useAppStore.getState().selectRoute(seeded[1].route.id);
    useAppStore.getState().selectRoute(seeded[2].route.id);
    useAppStore.getState().selectRoute(seeded[3].route.id);

    await new Promise((resolve) => setTimeout(resolve, 400));

    expect(refine).toHaveBeenCalledTimes(1);
    expect(refine).toHaveBeenCalledWith(
      'token-cccccccccccccccccccccccc',
      seeded[3].route.id,
    );
  });
});

describe('PR #18 재현 — 실패 후보 재선택이 즉시 다시 호출', () => {
  it('실패 직후 같은 후보를 다시 선택해도 추가 호출이 없어야 한다', async () => {
    const seeded = seedResults('token-dddddddddddddddddddddddd');
    const targetId = seeded[1].route.id;
    const refine = vi
      .spyOn(adapters.routes, 'refineTransit')
      .mockRejectedValue(new Error('timeout'));

    useAppStore.getState().selectRoute(targetId);
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(refine).toHaveBeenCalledTimes(1);

    useAppStore.getState().selectRoute(seeded[0].route.id);
    useAppStore.getState().selectRoute(targetId);
    await new Promise((resolve) => setTimeout(resolve, 400));

    expect(refine).toHaveBeenCalledTimes(1);
  });
});
