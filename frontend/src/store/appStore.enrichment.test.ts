import { afterEach, describe, expect, it, vi } from 'vitest';
import { adapters } from '@/adapters';
import { findPlace } from '@/data/places';
import { demoCandidates } from '@/data/routes';
import { WEATHER_SCENARIOS } from '@/data/weather';
import { recommendRoutes } from '@/scoring/engine';
import { useAppStore } from './appStore';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('경로 사전계산 결과 갱신', () => {
  it('화면 로딩을 다시 켜지 않고 선택한 의미상 같은 경로를 유지한다', async () => {
    const baseline = recommendRoutes(
      demoCandidates(),
      WEATHER_SCENARIOS.normal,
      'general',
    );
    const enriched = baseline.map((item, index) => ({
      ...item,
      route: {
        ...item.route,
        id: `enriched-${index}`,
        geometryQuality: 'exact' as const,
      },
      score: {
        ...item.score,
        routeId: `enriched-${index}`,
      },
    }));
    vi.spyOn(adapters.routes, 'recommend').mockResolvedValue(enriched);
    useAppStore.setState({
      origin: findPlace('gu-office') ?? null,
      destination: findPlace('seomyeon-stn') ?? null,
      profile: 'general',
      weatherScenario: 'normal',
      options: {},
      candidates: baseline.map(({ route }) => route),
      recommendations: baseline,
      selectedRouteId: baseline[1].route.id,
      loading: false,
      error: null,
    });

    await useAppStore.getState().refreshEnrichment();

    expect(useAppStore.getState().loading).toBe(false);
    expect(useAppStore.getState().selectedRouteId).toBe(
      enriched[1].route.id,
    );
    expect(useAppStore.getState().recommendations).toEqual(enriched);
  });
});
