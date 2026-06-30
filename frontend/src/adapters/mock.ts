import type { Adapters } from './types';
import { searchPlacesByName } from '@/data/places';
import { getRouteCandidates } from '@/data/routes';
import { BUS_STOP_LIST, getArrivals } from '@/data/busArrivals';
import { DEFAULT_WEATHER, WEATHER_SCENARIOS } from '@/data/weather';

/** 네트워크 지연 시뮬레이션 */
const delay = <T>(value: T, ms = 180): Promise<T> =>
  new Promise((resolve) => setTimeout(() => resolve(value), ms));

/** mock 어댑터 묶음. 모든 데이터는 src/data 의 부산진구 mock 에서 온다. */
export const mockAdapters: Adapters = {
  places: {
    searchPlaces: (query) => delay(searchPlacesByName(query)),
  },
  routes: {
    getCandidates: (origin, dest) => delay(getRouteCandidates(origin, dest), 260),
  },
  bus: {
    getArrivals: (stopId) => delay(getArrivals(stopId)),
    listStops: () => delay(BUS_STOP_LIST),
  },
  weather: {
    getCurrent: (scenario) =>
      delay(WEATHER_SCENARIOS[scenario ?? DEFAULT_WEATHER]),
  },
};
