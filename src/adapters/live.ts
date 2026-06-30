import type { Adapters } from './types';
import type { BusStopArrivals, Place, RouteCandidate, WeatherCondition } from '@/types';
import type { WeatherScenarioId } from '@/data/weather';

/**
 * 실 API(Python FastAPI 백엔드) 어댑터.
 * VITE_DATA_SOURCE=live 일 때 사용. 백엔드는 camelCase JSON 으로 응답하여 도메인 타입과 호환.
 * 기본 베이스 URL: http://localhost:8000 (VITE_API_BASE 로 변경 가능)
 */
const BASE = (import.meta.env.VITE_API_BASE ?? 'http://localhost:8000').replace(/\/$/, '');

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);
  return (await res.json()) as T;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`POST ${path} → ${res.status}`);
  return (await res.json()) as T;
}

export const liveAdapters: Adapters = {
  places: {
    searchPlaces: (query) =>
      getJson<Place[]>(`/api/places/search?q=${encodeURIComponent(query)}`),
  },
  routes: {
    getCandidates: (origin, dest) =>
      postJson<RouteCandidate[]>('/api/routes/candidates', {
        origin,
        destination: dest,
      }),
  },
  bus: {
    getArrivals: async (stopId) => {
      const res = await fetch(`${BASE}/api/bus/arrivals/${encodeURIComponent(stopId)}`);
      if (res.status === 404) return undefined;
      if (!res.ok) throw new Error(`bus arrivals → ${res.status}`);
      return (await res.json()) as BusStopArrivals;
    },
    listStops: () => getJson<BusStopArrivals[]>('/api/bus/stops'),
  },
  weather: {
    getCurrent: (scenario?: WeatherScenarioId) =>
      getJson<WeatherCondition>(`/api/weather?scenario=${scenario ?? 'normal'}`),
  },
};
