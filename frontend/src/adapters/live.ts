import type { Adapters } from './types';
import type { BusStopArrivals, Place, RouteCandidate, ScoredRoute, WeatherCondition } from '@/types';
import type { WeatherScenarioId } from '@/data/weather';
import { API_BASE, throwApiError } from '@/api/http';
import { hasKakaoKey } from '@/map/kakaoLoader';
import { searchKakaoPlaces } from '@/map/kakaoPlaces';

/**
 * 실 API(Python FastAPI 백엔드) 어댑터.
 * VITE_DATA_SOURCE=live 일 때 사용. 백엔드는 camelCase JSON 으로 응답하여 도메인 타입과 호환.
 * 운영 빌드는 같은 출처의 /api를 사용하고, 로컬 개발은 VITE_API_BASE로 변경 가능.
 */
const DEFAULT_TIMEOUT_MS = 7000;
const ROUTE_TIMEOUT_MS = 20000;

/** 타임아웃이 있는 fetch (백엔드 무응답 시 무한 대기 방지) */
async function fetchWithTimeout(
  path: string,
  init?: RequestInit,
  timeoutMs = DEFAULT_TIMEOUT_MS,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(`${API_BASE}${path}`, {
      credentials: 'include',
      ...init,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetchWithTimeout(path);
  if (!res.ok) await throwApiError(res, '정보를 불러오지 못했습니다');
  return (await res.json()) as T;
}

async function searchBackendPlaces(query: string): Promise<Place[]> {
  const res = await fetchWithTimeout(
    `/api/places/search?q=${encodeURIComponent(query)}`,
  );
  if (!res.ok) await throwApiError(res, '장소를 검색하지 못했습니다');
  if (res.headers.get('X-Place-Search-Source') !== 'kakao-rest') {
    throw new Error('KAKAO_PLACE_SEARCH_DEMO_SOURCE');
  }
  return (await res.json()) as Place[];
}

async function searchLivePlaces(query: string): Promise<Place[]> {
  if (hasKakaoKey()) {
    try {
      return await searchKakaoPlaces(query);
    } catch {
      // JavaScript SDK의 허용 도메인·일시 네트워크 오류 시에도
      // 출처가 검증된 Kakao REST 결과만 대체 경로로 허용한다.
    }
  }
  return searchBackendPlaces(query);
}

async function postJson<T>(
  path: string,
  body: unknown,
  timeoutMs = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  const res = await fetchWithTimeout(
    path,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
    timeoutMs,
  );
  if (!res.ok) await throwApiError(res, '요청을 처리하지 못했습니다');
  return (await res.json()) as T;
}

export const liveAdapters: Adapters = {
  places: {
    // JavaScript 키가 있는 웹/PWA는 Kakao Places SDK를 직접 사용한다.
    // SDK가 실패하거나 키가 없는 환경은 출처가 확인된 REST Local API를 사용한다.
    // live UI에서 demo 응답을 실제 Kakao 검색처럼 표시하지 않는다.
    searchPlaces: searchLivePlaces,
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
      }, ROUTE_TIMEOUT_MS),
    refreshShade: (current, profile, _weatherScenario, options, topN = 3) => {
      const routeSetToken = current[0]?.routeSetToken;
      if (!routeSetToken) {
        return Promise.reject(new Error('ROUTE_SET_TOKEN_MISSING'));
      }
      return postJson<ScoredRoute[]>('/api/routes/refresh-shade', {
        routeSetToken,
        profile,
        options,
        topN,
      }, ROUTE_TIMEOUT_MS);
    },
  },
  bus: {
    getArrivals: async (stopId) => {
      const res = await fetchWithTimeout(
        `/api/bus/arrivals/${encodeURIComponent(stopId)}`,
      );
      if (res.status === 404) return undefined;
      if (!res.ok) await throwApiError(res, '버스 도착 정보를 불러오지 못했습니다');
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
