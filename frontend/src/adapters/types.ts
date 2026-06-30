import type {
  BusStopArrivals,
  Place,
  RouteCandidate,
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
