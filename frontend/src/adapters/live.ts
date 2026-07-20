import type { Adapters } from './types';
import type { BusStopArrivals, Place, RouteCandidate, ScoredRoute, WeatherCondition } from '@/types';
import type { WeatherScenarioId } from '@/data/weather';

/**
 * 실 API(Python FastAPI 백엔드) 어댑터.
 * VITE_DATA_SOURCE=live 일 때 사용. 백엔드는 camelCase JSON 으로 응답하여 도메인 타입과 호환.
 * 기본 베이스 URL: http://localhost:8002 (VITE_API_BASE 로 변경 가능)
 */
const BASE = (import.meta.env.VITE_API_BASE ?? 'http://localhost:8002').replace(/\/$/, '');
const TIMEOUT_MS = 7000;

/** 타임아웃이 있는 fetch (백엔드 무응답 시 무한 대기 방지) */
async function fetchWithTimeout(path: string, init?: RequestInit): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    return await fetch(`${BASE}${path}`, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetchWithTimeout(path);
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);
  return (await res.json()) as T;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetchWithTimeout(path, {
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
    recommend: (origin, dest, profile, weatherScenario, options, topN = 3) =>
      postJson<ScoredRoute[]>('/api/routes/recommend', {
        origin,
        destination: dest,
        profile,
        weatherScenario,
        options,
        topN,
      }),
  },
  bus: {
    getArrivals: async (stopId) => {
      const res = await fetchWithTimeout(
        `/api/bus/arrivals/${encodeURIComponent(stopId)}`,
      );
      if (res.status === 404) return undefined;
      if (!res.ok) throw new Error(`bus arrivals → ${res.status}`);
      return (await res.json()) as BusStopArrivals;
    },
    listStops: (query = '') =>
      getJson<BusStopArrivals[]>(`/api/bus/stops?q=${encodeURIComponent(query)}`),
  },
  weather: {
    getCurrent: (scenario?: WeatherScenarioId) =>
      getJson<WeatherCondition>(`/api/weather?scenario=${scenario ?? 'normal'}`),
  },
};
