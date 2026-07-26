import type {
  BusStopArrivals,
  Place,
  ProfileId,
  RouteCandidate,
  ScoredRoute,
  ScoringOptions,
  TransitRefinement,
  WeatherCondition,
} from '@/types';
import type { WeatherScenarioId } from '@/data/weather';

/**
 * 외부 데이터 어댑터 인터페이스.
 * mock 구현과 live(실 API) 구현이 동일 시그니처를 공유한다.
 * → 실제 키 발급 시 mock.ts 대신 live.ts 만 교체하면 된다.
 */
export interface PlacesAdapter {
  /** 장소 검색(Kakao 키워드 검색에 대응) */
  searchPlaces(query: string): Promise<Place[]>;
}

export interface RouteAdapter {
  /** 출발/도착지 기반 경로 후보 생성 */
  getCandidates(origin: Place, dest: Place): Promise<RouteCandidate[]>;
  /**
   * 후보 생성 + 채점을 한 번에 수행한 추천 결과.
   * live: 백엔드 /api/routes/recommend (AI_SERVER_URL 설정 시 ai/ 파이프라인 위임).
   * mock: 로컬 scoring/engine 으로 즉시 채점(동일 인터페이스 유지용).
   */
  recommend(
    origin: Place,
    dest: Place,
    profile: ProfileId,
    weatherScenario: WeatherScenarioId,
    options: ScoringOptions,
    topN?: number,
  ): Promise<ScoredRoute[]>;
  /**
   * 현재 서버 후보군을 유지한 채 시간별 그늘과 순위만 갱신한다.
   * 경로 공급자 재호출 없이 서버가 발급한 routeSetToken을 사용한다.
   */
  refreshShade(
    current: ScoredRoute[],
    profile: ProfileId,
    weatherScenario: WeatherScenarioId,
    options: ScoringOptions,
    topN?: number,
  ): Promise<ScoredRoute[]>;
  /**
   * 기존 추천 카드에서 선택한 후보의 대중교통 표시 선형만 정밀화한다.
   * 재검색·재순위화 없이 해당 후보 geometry만 patch되며,
   * 정밀화를 지원하지 않는 모드(mock)는 null을 반환한다.
   */
  refineTransit(
    routeSetToken: string,
    routeId: string,
  ): Promise<TransitRefinement | null>;
}

export interface BusAdapter {
  /** 정류장 도착 정보(저상버스 여부 포함) */
  getArrivals(stopId: string): Promise<BusStopArrivals | undefined>;
  /** 정류소명 또는 5자리 ARS 번호 검색. 데모에서는 전체 픽스처를 반환한다. */
  listStops(query?: string): Promise<BusStopArrivals[]>;
}

export interface WeatherAdapter {
  /** 현재 날씨(데모는 시나리오 id로 조회) */
  getCurrent(scenario?: WeatherScenarioId): Promise<WeatherCondition>;
}

export interface Adapters {
  places: PlacesAdapter;
  routes: RouteAdapter;
  bus: BusAdapter;
  weather: WeatherAdapter;
}
