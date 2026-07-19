import type {
  BusStopArrivals,
  Place,
  ProfileId,
  RouteCandidate,
  ScoredRoute,
  ScoringOptions,
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
}

export interface BusAdapter {
  /** 정류장 도착 정보(저상버스 여부 포함) */
  getArrivals(stopId: string): Promise<BusStopArrivals | undefined>;
  /** 전체 정류장 목록 */
  listStops(): Promise<BusStopArrivals[]>;
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
