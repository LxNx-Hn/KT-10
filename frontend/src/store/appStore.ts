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

/**
 * 후보 집합 자체가 바뀌는 시점(새 검색·OD 변경)마다 증가한다.
 * 이전 세대에서 시작된 정밀화 응답이 새 결과를 덮지 않게 하는 기준이다.
 * 재순위화(rescore)는 같은 route-set을 유지하므로 증가시키지 않는다.
 */
let recommendationGeneration = 0;

function beginNewCandidateGeneration(): number {
  recommendationGeneration += 1;
  refinementCooldownUntil.clear();
  return recommendationGeneration;
}

/**
 * 후보별 대중교통 정밀화 in-flight 단일화.
 * route ID만으로는 서로 다른 검색의 동일 semantic 후보를 구분할 수 없어
 * route-set token을 함께 사용한다.
 */
const transitRefinementInFlight = new Set<string>();

export function routeRefinementKey(
  routeSetToken: string,
  routeId: string,
): string {
  return `${routeSetToken}\u001f${routeId}`;
}

/**
 * 카드 선택이 이 시간만큼 유지된 뒤에만 정밀화를 시작한다.
 * carousel을 빠르게 넘길 때 지나친 후보마다 loadLane을 호출하지 않는다.
 */
const REFINEMENT_DEBOUNCE_MS = 200;
let pendingRefinementTimer: ReturnType<typeof setTimeout> | undefined;

/**
 * 정밀화가 실패한 후보는 일정 시간 다시 요청하지 않는다.
 * 실패 카드를 반복 선택하는 것만으로 공급자 호출이 폭주하지 않게 한다.
 * 서버가 Retry-After를 주면 그 값을 우선한다.
 */
const REFINEMENT_FAILURE_COOLDOWN_MS = 60_000;
const refinementCooldownUntil = new Map<string, number>();

function refinementCooldownActive(key: string): boolean {
  const until = refinementCooldownUntil.get(key);
  if (until === undefined) return false;
  if (Date.now() >= until) {
    refinementCooldownUntil.delete(key);
    return false;
  }
  return true;
}

/** 서버가 알려준 재시도 대기시간(초)을 읽는다. 없으면 기본 cooldown. */
function retryAfterMs(error: unknown): number {
  const seconds = (error as { retryAfterSeconds?: unknown })
    ?.retryAfterSeconds;
  return typeof seconds === 'number' && Number.isFinite(seconds) && seconds > 0
    ? seconds * 1000
    : REFINEMENT_FAILURE_COOLDOWN_MS;
}

function cancelPendingRefinement(): void {
  if (pendingRefinementTimer !== undefined) {
    clearTimeout(pendingRefinementTimer);
    pendingRefinementTimer = undefined;
  }
}

/** 대중교통 구간이 아직 estimated인 후보만 정밀화 대상이다. */
function needsTransitRefinement(route: RouteCandidate): boolean {
  return route.segments.some(
    (segment) =>
      (segment.mode === 'bus' || segment.mode === 'subway') &&
      segment.geometryQuality !== 'exact',
  );
}

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

function routeSemanticKey(route: RouteCandidate): string {
  return JSON.stringify({
    summary: route.summary,
    segments: route.segments.map((segment) => ({
      mode: segment.mode,
      busRouteName: segment.busRouteName ?? null,
      stationName: segment.stationName ?? null,
      description: segment.description,
    })),
  });
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
  /** route-set token + route ID로 구분한 진행 중 정밀화 key 목록. */
  refiningRouteKeys: string[];

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
  setDepartureAt: (value: string) => Promise<boolean>;
  toggleLargeUi: () => void;
  clearError: () => void;
  selectRoute: (id: string | null) => void;
  setLastSpoken: (s: string) => void;
  loadDemoOd: () => void;
  search: () => Promise<void>;
  rescore: () => Promise<void>;
  refreshShade: () => Promise<boolean>;
  invalidateTransitRefinements: () => void;

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
  refiningRouteKeys: [],

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
    beginNewCandidateGeneration();
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
    beginNewCandidateGeneration();
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
  /**
   * 카드 선택은 즉시 반영하고, 선택한 후보의 대중교통 표시 선형이 아직
   * estimated면 서버 refinement로 해당 후보 geometry만 patch한다.
   * 재검색·재순위화·점수 변경은 발생하지 않는다.
   */
  selectRoute: (selectedRouteId) => {
    // 선택 상태는 즉시 반영하고, 외부 호출만 debounce한다.
    set({ selectedRouteId });
    cancelPendingRefinement();
    if (!selectedRouteId) return;
    const { recommendations } = get();
    const selected = recommendations.find(
      ({ route }) => route.id === selectedRouteId,
    );
    const routeSetToken = selected?.routeSetToken;
    if (
      !selected
      || !routeSetToken
      || !needsTransitRefinement(selected.route)
    ) {
      return;
    }
    const key = routeRefinementKey(routeSetToken, selectedRouteId);
    if (transitRefinementInFlight.has(key)) return;
    // 최근 실패한 후보는 cooldown이 끝날 때까지 다시 요청하지 않는다.
    if (refinementCooldownActive(key)) return;

    // 응답 적용 조건을 요청 시작 시점에 고정한다.
    const capturedGeneration = recommendationGeneration;
    const capturedToken = routeSetToken;
    const capturedRouteId = selectedRouteId;

    pendingRefinementTimer = setTimeout(() => {
      pendingRefinementTimer = undefined;
      // debounce 대기 중 선택이나 후보 집합이 바뀌었으면 시작하지 않는다.
      if (
        get().selectedRouteId !== capturedRouteId
        || recommendationGeneration !== capturedGeneration
        || transitRefinementInFlight.has(key)
        || refinementCooldownActive(key)
      ) {
        return;
      }
      startRefinement();
    }, REFINEMENT_DEBOUNCE_MS);

    function startRefinement() {
      transitRefinementInFlight.add(key);
      set((state) => ({
        refiningRouteKeys: state.refiningRouteKeys.includes(key)
          ? state.refiningRouteKeys
          : [...state.refiningRouteKeys, key],
      }));
      void adapters.routes
        .refineTransit(capturedToken, capturedRouteId)
        .then((refined) => {
          if (!refined || refined.routeId !== capturedRouteId) return;
          // 요청을 시작한 후보 집합이 아직 화면에 남아 있을 때만 반영한다.
          if (recommendationGeneration !== capturedGeneration) return;
          const current = get().recommendations.find(
            ({ route }) => route.id === capturedRouteId,
          );
          if (!current || current.routeSetToken !== capturedToken) return;

          const patch = (route: RouteCandidate): RouteCandidate =>
            route.id === capturedRouteId
              ? {
                  ...route,
                  path: refined.path,
                  segments: refined.segments,
                  geometryQuality: refined.geometryQuality,
                }
              : route;
          refinementCooldownUntil.delete(key);
          set((state) => ({
            candidates: state.candidates.map(patch),
            recommendations: state.recommendations.map((item) => (
              item.route.id === capturedRouteId
                ? { ...item, route: patch(item.route) }
                : item
            )),
          }));
        })
        .catch((error: unknown) => {
          // 정밀화 실패 시 estimated 표시를 유지하고 cooldown을 건다.
          // 전체 재검색이나 오류 화면 전환은 하지 않는다.
          refinementCooldownUntil.set(key, Date.now() + retryAfterMs(error));
        })
        .finally(() => {
          transitRefinementInFlight.delete(key);
          set((state) => ({
            refiningRouteKeys: state.refiningRouteKeys.filter(
              (routeKey) => routeKey !== key,
            ),
          }));
        });
    }
  },
  setLastSpoken: (lastSpoken) => set({ lastSpoken }),

  /** 데모 기본 OD(부산진구청 → 서면역) 채우기 */
  loadDemoOd: () => {
    const origin = findPlace(DEMO_OD.originId) ?? null;
    const destination = findPlace(DEMO_OD.destinationId) ?? null;
    beginRecommendationRequest();
    beginNewCandidateGeneration();
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
    beginNewCandidateGeneration();
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
    const {
      origin,
      destination,
      profile,
      options,
      selectedRouteId,
      recommendations: previous,
    } = get();
    if (!origin || !destination || !previous.length) return;
    const requestGeneration = beginRecommendationRequest();
    set({ loading: true, error: null });
    try {
      // 프로필·조건 변경은 경로 후보를 다시 수집하지 않는다. 서버가 보관한
      // route-set을 그대로 재순위화하므로 ODsay·TMAP 호출이 없다.
      const recommendations = await adapters.routes.rescore(
        previous,
        profile,
        get().weatherScenario,
        options,
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

  invalidateTransitRefinements: () => {
    cancelPendingRefinement();
    beginNewCandidateGeneration();
  },

  /** 기존 후보군을 유지하고 선택 시각의 그늘과 순위만 갱신한다. */
  refreshShade: async () => {
    const {
      profile,
      weatherScenario,
      options,
      selectedRouteId,
      recommendations: previous,
    } = get();
    if (!previous.length) return false;
    const requestGeneration = beginRecommendationRequest();
    const previousSelected = previous.find(
      ({ route }) => route.id === selectedRouteId,
    );
    const previousSemanticKey = previousSelected
      ? routeSemanticKey(previousSelected.route)
      : null;
    try {
      const recommendations = await adapters.routes.refreshShade(
        previous,
        profile,
        weatherScenario,
        options,
        previous.length,
      );
      if (
        !isLatestRecommendationRequest(requestGeneration)
        || !recommendations.length
      ) {
        return false;
      }
      const semanticMatch = previousSemanticKey
        ? recommendations.find(
          ({ route }) => routeSemanticKey(route) === previousSemanticKey,
        )
        : undefined;
      const directMatch = recommendations.find(
        ({ route }) => route.id === selectedRouteId,
      );
      set({
        candidates: recommendations.map(({ route }) => route),
        recommendations,
        selectedRouteId: (
          semanticMatch
          ?? directMatch
          ?? serverRankedRecommendations(recommendations)[0]
        )?.route.id ?? null,
        error: null,
      });
      return true;
    } catch (error) {
      if (!isLatestRecommendationRequest(requestGeneration)) return false;
      set({
        error: toUserMessage(
          error,
          '그늘 계산 시각을 갱신하지 못했습니다. 경로를 다시 검색해 주세요.',
        ),
      });
      return false;
    }
  },

  /* ── 음성 챗봇 연동 액션 (요구사항 §9) ── */

  /** 출발지가 비어 있으면 브라우저의 실제 현재 위치 권한을 요청한다. */
  ensureOrigin: () => {
    if (get().origin) return;
    get().useCurrentLocation();
  },

  setDepartureAt: async (departureAt) => {
    const previousDepartureAt = get().options.departureAt;
    const restartPendingSearch = get().loading && !get().candidates.length;
    set((s) => ({ options: { ...s.options, departureAt } }));
    if (get().candidates.length) {
      const refreshed = await get().refreshShade();
      if (!refreshed && get().options.departureAt === departureAt) {
        set((s) => ({
          options: { ...s.options, departureAt: previousDepartureAt },
        }));
      }
      return refreshed;
    } else if (restartPendingSearch && get().origin && get().destination) {
      await get().search();
    }
    return true;
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
