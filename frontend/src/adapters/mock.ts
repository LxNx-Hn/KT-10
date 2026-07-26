import type { Adapters } from './types';
import { searchPlacesByName } from '@/data/places';
import { getRouteCandidates } from '@/data/routes';
import { BUS_STOP_LIST, getArrivals } from '@/data/busArrivals';
import { DEFAULT_WEATHER, WEATHER_SCENARIOS } from '@/data/weather';
import { recommendRoutes } from '@/scoring/engine';

/** 데모 UI 비동기 상태 확인용 지연 */
const delay = <T>(value: T, ms = 180): Promise<T> =>
  new Promise((resolve) => setTimeout(() => resolve(value), ms));

/** 회귀검증용 고정 데모 어댑터. 임의 OD 경로는 만들지 않는다. */
export const mockAdapters: Adapters = {
  places: {
    searchPlaces: (query) => delay(searchPlacesByName(query)),
  },
  routes: {
    getCandidates: (origin, dest) => delay(getRouteCandidates(origin, dest), 260),
    recommend: async (origin, dest, profile, weatherScenario, options, topN = 5) => {
      const candidates = await delay(getRouteCandidates(origin, dest), 260);
      if (!candidates.length) throw new Error('고정 데모 OD 외 경로는 live 모드에서만 조회할 수 있습니다.');
      const weather = WEATHER_SCENARIOS[weatherScenario ?? DEFAULT_WEATHER];
      return recommendRoutes(candidates, weather, profile, options, topN);
    },
    refreshShade: async (current, profile, weatherScenario, options, topN = 5) => {
      const weather = WEATHER_SCENARIOS[weatherScenario ?? DEFAULT_WEATHER];
      return delay(
        recommendRoutes(
          current.map(({ route }) => route),
          weather,
          profile,
          options,
          topN,
        ),
      );
    },
    // 고정 데모 경로는 이미 확정 geometry이므로 정밀화가 없다.
    refineTransit: () => Promise.resolve(null),
  },
  bus: {
    getArrivals: (stopId) => delay(getArrivals(stopId)),
    listStops: (query = '') => delay(
      query.trim()
        ? BUS_STOP_LIST.filter((stop) => stop.stopName.includes(query.trim()) || stop.stopId === query.trim())
        : BUS_STOP_LIST,
    ),
  },
  weather: {
    getCurrent: (scenario) =>
      delay(WEATHER_SCENARIOS[scenario ?? DEFAULT_WEATHER]),
  },
};
