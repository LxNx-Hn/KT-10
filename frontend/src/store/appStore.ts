import { create } from 'zustand';
import type {
  Place,
  ProfileId,
  RouteCandidate,
  ScoredRoute,
  ScoringOptions,
  WeatherCondition,
} from '@/types';
import { adapters } from '@/adapters';
import { PROFILES } from '@/config/profiles';
import { DEFAULT_WEATHER, type WeatherScenarioId } from '@/data/weather';
import { findPlace } from '@/data/places';
import { DEMO_OD } from '@/data/routes';
import { isInDistrict } from '@/config/district';
import type { WeatherAvoidanceMode } from '@/voice/intents';
import { toUserMessage } from '@/api/http';
import { serverRankedRecommendations } from '@/utils/routes';

/** 날씨 회피 모드 → 데모 날씨 시나리오 매핑 */
const WEATHER_MODE_SCENARIO: Record<WeatherAvoidanceMode, WeatherScenarioId | null> = {
  heat: 'heatwave',
  rain: 'rain',
  cold: 'coldwave',
  dust: 'dust',
  general: null,
};

function defaultDepartureAt(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  const hour = String(now.getHours()).padStart(2, '0');
  const minute = String(now.getMinutes()).padStart(2, '0');
  return `${year}-${month}-${day}T${hour}:${minute}`;
}

let recommendationRequestGeneration = 0;
let weatherRequestGeneration = 0;

function beginRecommendationRequest(): number {
  recommendationRequestGeneration += 1;
  return recommendationRequestGeneration;
}

function isLatestRecommendationRequest(generation: number): boolean {
  return generation === recommendationRequestGeneration;
}

function beginWeatherRequest(): number {
  weatherRequestGeneration += 1;
  return weatherRequestGeneration;
}

export type ToggleableScoringOption =
  | 'carryLuggage'
  | 'stroller'
  | 'lowFloorPriority'
  | 'weatherAvoid'
  | 'avoidStairs'
  | 'shadePriority'
  | 'minimizeTransfers';

interface AppState {
  /* 입력 */
  profile: ProfileId;
  origin: Place | null;
  destination: Place | null;
  weatherScenario: WeatherScenarioId;
  weather: WeatherCondition | null;
  options: ScoringOptions;

  /* 결과 */
  candidates: RouteCandidate[];
  recommendations: ScoredRoute[];
  selectedRouteId: string | null;

  /* UI/상태 */
  largeUi: boolean;
  loading: boolean;
  error: string | null;
  lastSpoken: string;

  /* 액션 */
  setProfile: (p: ProfileId) => void;
  setOrigin: (p: Place | null) => void;
  setDestination: (p: Place | null) => void;
  setWeatherScenario: (w: WeatherScenarioId) => Promise<void>;
  setScoringOption: (key: ToggleableScoringOption, enabled: boolean) => void;
  toggleCarryLuggage: () => void;
  toggleStroller: () => void;
  toggleLowFloorPriority: () => void;
  toggleWeatherAvoid: () => void;
  toggleAvoidStairs: () => void;
  toggleShadePriority: () => void;
  toggleMinimizeTransfers: () => void;
  setDepartureAt: (value: string) => void;
  toggleLargeUi: () => void;
  clearError: () => void;
  selectRoute: (id: string | null) => void;
  setLastSpoken: (s: string) => void;
  loadDemoOd: () => void;
  search: () => Promise<void>;
  rescore: () => Promise<void>;

  /* 음성 챗봇 연동 액션 (요구사항 §9) */
  ensureOrigin: () => void;
  useCurrentLocation: () => void;
  setDestinationFromVoice: (destination: string) => Promise<Place | null>;
  setOriginFromVoice: (origin: string) => Promise<Place | null>;
  setProfileFromVoice: (p: ProfileId) => void;
  enableLowFloorBusPriority: () => void;
  enableWeatherAvoidance: (mode: WeatherAvoidanceMode) => Promise<void>;
  enableStairAvoidance: () => void;
  recalculateRoutes: () => Promise<void>;
}

export const useAppStore = create<AppState>((set, get) => ({
  profile: 'general',
  origin: null,
  destination: null,
  weatherScenario: DEFAULT_WEATHER,
  weather: null,
  options: { departureAt: defaultDepartureAt() },

  candidates: [],
  recommendations: [],
  selectedRouteId: null,

  largeUi: false,
  loading: false,
  error: null,
  lastSpoken: '',

  setProfile: (profile) => {
    const restartPendingSearch = get().loading && !get().candidates.length;
    set({ profile, largeUi: PROFILES[profile].prefersLargeUi || get().largeUi });
    if (get().candidates.length) {
      void get().rescore();
    } else if (restartPendingSearch && get().origin && get().destination) {
      void get().search();
    }
  },

  setOrigin: (origin) => {
    beginRecommendationRequest();
    set({
      origin,
      candidates: [],
      recommendations: [],
      selectedRouteId: null,
      loading: false,
      error: null,
    });
  },
  setDestination: (destination) => {
    beginRecommendationRequest();
    set({
      destination,
      candidates: [],
      recommendations: [],
      selectedRouteId: null,
      loading: false,
      error: null,
    });
  },

  setWeatherScenario: async (weatherScenario) => {
    const weatherGeneration = beginWeatherRequest();
    const restartPendingRecommendation = get().loading;
    if (restartPendingRecommendation) beginRecommendationRequest();
    try {
      const weather = await adapters.weather.getCurrent(weatherScenario);
      if (weatherGeneration !== weatherRequestGeneration) return;
      set({ weatherScenario, weather, error: null });
      if (get().candidates.length) {
        await get().rescore();
      } else if (
        restartPendingRecommendation
        && get().origin
        && get().destination
      ) {
        await get().search();
      } else if (restartPendingRecommendation) {
        set({ loading: false });
      }
    } catch (error) {
      if (weatherGeneration !== weatherRequestGeneration) return;
      set({
        loading: false,
        error: toUserMessage(error, '날씨 정보를 불러오지 못했습니다.'),
      });
    }
  },

  toggleCarryLuggage: () => {
    get().setScoringOption('carryLuggage', !get().options.carryLuggage);
  },

  toggleStroller: () => {
    get().setScoringOption('stroller', !get().options.stroller);
  },

  toggleLowFloorPriority: () => {
    get().setScoringOption('lowFloorPriority', !get().options.lowFloorPriority);
  },

  toggleWeatherAvoid: () => {
    get().setScoringOption('weatherAvoid', !get().options.weatherAvoid);
  },

  toggleAvoidStairs: () => {
    get().setScoringOption('avoidStairs', !get().options.avoidStairs);
  },

  toggleShadePriority: () => {
    get().setScoringOption('shadePriority', !get().options.shadePriority);
  },

  toggleMinimizeTransfers: () => {
    get().setScoringOption('minimizeTransfers', !get().options.minimizeTransfers);
  },

  setScoringOption: (key, enabled) => {
    const restartPendingSearch = get().loading && !get().candidates.length;
    set((state) => ({ options: { ...state.options, [key]: enabled } }));
    if (get().candidates.length) {
      void get().rescore();
    } else if (restartPendingSearch && get().origin && get().destination) {
      void get().search();
    }
  },

  toggleLargeUi: () => set((s) => ({ largeUi: !s.largeUi })),
  clearError: () => set({ error: null }),
  selectRoute: (selectedRouteId) => set({ selectedRouteId }),
  setLastSpoken: (lastSpoken) => set({ lastSpoken }),

  /** 데모 기본 OD(부산진구청 → 서면역) 채우기 */
  loadDemoOd: () => {
    const origin = findPlace(DEMO_OD.originId) ?? null;
    const destination = findPlace(DEMO_OD.destinationId) ?? null;
    beginRecommendationRequest();
    set({
      origin,
      destination,
      candidates: [],
      recommendations: [],
      selectedRouteId: null,
      loading: false,
      error: null,
    });
  },

  search: async () => {
    const requestGeneration = beginRecommendationRequest();
    const { origin, destination, profile, weatherScenario, options } = get();
    if (!origin || !destination) {
      set({ loading: false, error: '출발지와 도착지를 모두 선택해 주세요.' });
      return;
    }
    set({ loading: true, error: null });
    try {
      const [recommendations, weather] = await Promise.all([
        adapters.routes.recommend(origin, destination, profile, weatherScenario, options),
        adapters.weather.getCurrent(weatherScenario),
      ]);
      if (!isLatestRecommendationRequest(requestGeneration)) return;
      if (!recommendations.length) {
        set({
          candidates: [],
          recommendations: [],
          selectedRouteId: null,
          weather,
          loading: false,
          error: '조건에 맞는 경로 후보를 찾지 못했습니다. 출발지와 도착지를 확인해 주세요.',
        });
        return;
      }
      set({
        candidates: recommendations.map((r) => r.route),
        weather,
        recommendations,
        selectedRouteId: serverRankedRecommendations(recommendations)[0]?.route.id ?? null,
        loading: false,
      });
    } catch (error) {
      if (!isLatestRecommendationRequest(requestGeneration)) return;
      set({
        loading: false,
        error: toUserMessage(error, '경로를 불러오지 못했습니다. 다시 시도해 주세요.'),
      });
      console.error(error);
    }
  },

  /** 프로필/날씨/옵션 변경 시 서버(live) 또는 로컬(mock)에 재채점을 요청 */
  rescore: async () => {
    const { origin, destination, profile, weatherScenario, options, selectedRouteId } = get();
    if (!origin || !destination || !get().recommendations.length) return;
    const requestGeneration = beginRecommendationRequest();
    set({ loading: true, error: null });
    try {
      const recommendations = await adapters.routes.recommend(
        origin, destination, profile, weatherScenario, options,
      );
      if (!isLatestRecommendationRequest(requestGeneration)) return;
      if (!recommendations.length) {
        set({
          candidates: [],
          recommendations: [],
          selectedRouteId: null,
          loading: false,
          error: '변경한 조건에 맞는 경로 후보를 찾지 못했습니다.',
        });
        return;
      }
      const stillThere = recommendations.some((r) => r.route.id === selectedRouteId);
      set({
        candidates: recommendations.map((r) => r.route),
        recommendations,
        selectedRouteId: stillThere
          ? selectedRouteId
          : serverRankedRecommendations(recommendations)[0]?.route.id ?? null,
        loading: false,
      });
    } catch (error) {
      if (!isLatestRecommendationRequest(requestGeneration)) return;
      set({
        loading: false,
        error: toUserMessage(error, '변경한 조건으로 경로를 다시 계산하지 못했습니다.'),
      });
    }
  },

  /* ── 음성 챗봇 연동 액션 (요구사항 §9) ── */

  /** 출발지가 비어 있으면 브라우저의 실제 현재 위치 권한을 요청한다. */
  ensureOrigin: () => {
    if (get().origin) return;
    get().useCurrentLocation();
  },

  setDepartureAt: (departureAt) => {
    const restartPendingSearch = get().loading && !get().candidates.length;
    set((s) => ({ options: { ...s.options, departureAt } }));
    if (get().candidates.length) {
      void get().rescore();
    } else if (restartPendingSearch && get().origin && get().destination) {
      void get().search();
    }
  },

  /** 브라우저 Geolocation으로 확인된 부산 좌표만 출발지로 사용한다. */
  useCurrentLocation: () => {
    if (!navigator.geolocation) {
      set({ error: '이 브라우저에서는 현재 위치를 사용할 수 없습니다.' });
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const current = { lat: position.coords.latitude, lng: position.coords.longitude };
        if (!isInDistrict(current)) {
          set({ error: '현재 위치가 부산 서비스 범위 밖입니다.' });
          return;
        }
        get().setOrigin({
          id: 'current',
          name: '현재 위치',
          category: '현재 위치',
          ...current,
        });
      },
      () => set({ error: '현재 위치를 가져오지 못했습니다. 위치 권한을 확인해 주세요.' }),
      { enableHighAccuracy: true, timeout: 10000 },
    );
  },

  setDestinationFromVoice: async (destination) => {
    const results = await adapters.places.searchPlaces(destination);
    const place = results[0] ?? null;
    if (place) get().setDestination(place);
    return place;
  },

  setOriginFromVoice: async (origin) => {
    const results = await adapters.places.searchPlaces(origin);
    const place = results[0] ?? null;
    if (place) get().setOrigin(place);
    return place;
  },

  setProfileFromVoice: (p) => get().setProfile(p),

  enableLowFloorBusPriority: () => {
    get().setScoringOption('lowFloorPriority', true);
  },

  enableWeatherAvoidance: async (mode) => {
    get().setScoringOption('weatherAvoid', true);
    const scenario = WEATHER_MODE_SCENARIO[mode];
    if (scenario) {
      await get().setWeatherScenario(scenario); // 날씨 갱신 + 재채점 포함
    } else {
      get().rescore();
    }
  },

  enableStairAvoidance: () => {
    get().setScoringOption('avoidStairs', true);
  },

  recalculateRoutes: async () => {
    await get().search();
  },
}));
