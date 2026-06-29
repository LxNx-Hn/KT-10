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
import { recommendRoutes } from '@/scoring/engine';
import { PROFILES } from '@/config/profiles';
import { DEFAULT_WEATHER, type WeatherScenarioId } from '@/data/weather';
import { findPlace } from '@/data/places';
import { DEMO_OD } from '@/data/routes';

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
  toggleLowFloorPriority: () => void;
  toggleWeatherAvoid: () => void;
  toggleLargeUi: () => void;
  selectRoute: (id: string | null) => void;
  setLastSpoken: (s: string) => void;
  loadDemoOd: () => void;
  search: () => Promise<void>;
  rescore: () => void;
}

export const useAppStore = create<AppState>((set, get) => ({
  profile: 'general',
  origin: null,
  destination: null,
  weatherScenario: DEFAULT_WEATHER,
  weather: null,
  options: {},

  candidates: [],
  recommendations: [],
  selectedRouteId: null,

  largeUi: false,
  loading: false,
  error: null,
  lastSpoken: '',

  setProfile: (profile) => {
    set({ profile, largeUi: PROFILES[profile].prefersLargeUi || get().largeUi });
    if (get().candidates.length) get().rescore();
  },

  setOrigin: (origin) => set({ origin }),
  setDestination: (destination) => set({ destination }),

  setWeatherScenario: async (weatherScenario) => {
    const weather = await adapters.weather.getCurrent(weatherScenario);
    set({ weatherScenario, weather });
    if (get().candidates.length) get().rescore();
  },

  toggleLowFloorPriority: () => {
    set((s) => ({ options: { ...s.options, lowFloorPriority: !s.options.lowFloorPriority } }));
    if (get().candidates.length) get().rescore();
  },

  toggleWeatherAvoid: () => {
    set((s) => ({ options: { ...s.options, weatherAvoid: !s.options.weatherAvoid } }));
    if (get().candidates.length) get().rescore();
  },

  toggleLargeUi: () => set((s) => ({ largeUi: !s.largeUi })),
  selectRoute: (selectedRouteId) => set({ selectedRouteId }),
  setLastSpoken: (lastSpoken) => set({ lastSpoken }),

  /** 데모 기본 OD(부산진구청 → 서면역) 채우기 */
  loadDemoOd: () => {
    const origin = findPlace(DEMO_OD.originId) ?? null;
    const destination = findPlace(DEMO_OD.destinationId) ?? null;
    set({ origin, destination });
  },

  search: async () => {
    const { origin, destination, profile, weatherScenario, options } = get();
    if (!origin || !destination) {
      set({ error: '출발지와 도착지를 모두 선택해 주세요.' });
      return;
    }
    set({ loading: true, error: null });
    try {
      const [candidates, weather] = await Promise.all([
        adapters.routes.getCandidates(origin, destination),
        adapters.weather.getCurrent(weatherScenario),
      ]);
      const recommendations = recommendRoutes(candidates, weather, profile, options);
      set({
        candidates,
        weather,
        recommendations,
        selectedRouteId: recommendations[0]?.route.id ?? null,
        loading: false,
      });
    } catch (e) {
      set({ loading: false, error: '경로를 불러오지 못했습니다. 다시 시도해 주세요.' });
      console.error(e);
    }
  },

  /** 후보는 그대로, 프로필/날씨/옵션 변경 시 재채점만 수행 */
  rescore: () => {
    const { candidates, weather, profile, options, selectedRouteId } = get();
    if (!candidates.length || !weather) return;
    const recommendations = recommendRoutes(candidates, weather, profile, options);
    const stillThere = recommendations.some((r) => r.route.id === selectedRouteId);
    set({
      recommendations,
      selectedRouteId: stillThere ? selectedRouteId : recommendations[0]?.route.id ?? null,
    });
  },
}));
