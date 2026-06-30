/**
 * 도메인 핵심 타입 정의.
 * 점수화 엔진/어댑터/UI가 공유하는 단일 진실 공급원(SSOT).
 */

/* ───────────────────────── 프로필 ───────────────────────── */

export type ProfileId = 'general' | 'elderly' | 'child' | 'disabled';

export interface ProfileMeta {
  id: ProfileId;
  label: string; // 화면 표시명
  description: string;
  /** 큰 UI를 기본 적용할지 여부(고령자/아동) */
  prefersLargeUi: boolean;
}

/* ───────────────────────── 장소/좌표 ───────────────────────── */

export interface LatLng {
  lat: number;
  lng: number;
}

export interface Place extends LatLng {
  id: string;
  name: string;
  /** 카테고리: 지하철역, 정류장, 관공서 등 */
  category?: string;
  address?: string;
}

/* ───────────────────────── 경로 구간 ───────────────────────── */

export type SegmentMode = 'walk' | 'bus' | 'subway' | 'transfer';

/**
 * 3값 논리 정보. 접근성 데이터는 "있음/없음/미확인"을 구분해야 한다.
 * - true: 확인된 양호
 * - false: 확인된 불량(예: 일반버스, 계단만 존재)
 * - undefined: 정보 없음(미확인)
 */
export type Tristate = boolean | undefined;

export interface RouteSegment {
  id: string;
  mode: SegmentMode;
  /** 사람이 읽는 구간 설명 */
  description: string;
  durationMin: number;
  distanceM?: number;

  /* 보행 구간 속성 */
  outdoor?: boolean; // 실외 노출(날씨 영향)
  hasStairs?: boolean;
  stairsCount?: number;
  hasSlope?: boolean; // 경사로
  crosswalkCount?: number; // 횡단보도 수
  accidentRisk?: 'low' | 'medium' | 'high'; // 사고위험 구간

  /* 버스 구간 속성 */
  busRouteName?: string;
  /** 저상버스 여부(미확인 = undefined) */
  isLowFloorBus?: Tristate;
  waitMin?: number; // 대기시간

  /* 역/수직이동(승강기) 속성 */
  stationName?: string;
  /** 승강기 이용 가능 여부(미확인 = undefined) */
  hasElevator?: Tristate;
  /** 수직이동(층 이동)이 필요한 구간인지 */
  needsVerticalMove?: boolean;
}

export interface RouteCandidate {
  id: string;
  summary: string; // 예: "210번 버스 + 도보"
  origin: string;
  destination: string;
  segments: RouteSegment[];

  /* 집계값(어댑터가 계산해 채움) */
  totalDurationMin: number;
  totalWalkM: number;
  transferCount: number;
  /** 경로 폴리라인(지도 표시용) */
  path?: LatLng[];
}

/* ───────────────────────── 날씨 ───────────────────────── */

export type AirQuality = 'good' | 'moderate' | 'bad' | 'very_bad';
export type SkyCondition = 'clear' | 'cloudy' | 'rain' | 'snow';

export interface WeatherCondition {
  label: string; // 시나리오 이름(예: "폭염")
  tempC: number;
  feelsLikeC: number; // 체감온도
  precipitationMm: number; // 강수
  isHeatwave: boolean; // 폭염
  isColdwave: boolean; // 한파
  windMs: number; // 풍속
  pm10: number; // 미세먼지
  sky: SkyCondition;
  air: AirQuality;
}

/* ───────────────────────── 저상버스 도착 ───────────────────────── */

export interface BusArrival {
  routeName: string; // 예: "81"
  arrivalMin: number; // 도착까지 분
  isLowFloor: Tristate; // 저상버스 여부(미확인 가능)
  remainingStops?: number;
}

export interface BusStopArrivals {
  stopId: string;
  stopName: string;
  arrivals: BusArrival[];
}

/* ───────────────────────── 점수 ───────────────────────── */

/**
 * 모든 하위 점수는 "좋음 점수(goodness)" 0~100 으로 통일한다.
 * 100 = 가장 이상적, 0 = 가장 불리.
 * (보행 부담/날씨 위험은 화면 표시 시 100 - goodness 로 변환)
 */
export interface ScoreComponents {
  accessibility: number; // 접근성
  walkComfort: number; // 보행 편의(↔ 보행 부담)
  elevator: number; // 승강기 이용 가능성
  lowFloorBus: number; // 저상버스 이용 가능성
  weatherSafety: number; // 날씨 안전(↔ 날씨 위험)
  safety: number; // 안전성(사고/횡단)
  dataReliability: number; // 데이터 신뢰도
  timeEfficiency: number; // 시간 효율
}

export type LowFloorStatus = 'confirmed' | 'regular' | 'unknown' | 'none';

export interface RouteScore {
  routeId: string;
  components: ScoreComponents;
  /** 화면 표시용 파생값(높을수록 나쁨) */
  display: {
    walkBurden: number; // 보행 부담
    weatherRisk: number; // 날씨 위험
  };
  finalScore: number; // 최종 추천 점수 0~100
  lowFloorStatus: LowFloorStatus;
  reasons: string[]; // 추천 이유
  cautions: string[]; // 주의사항
  voiceSummary: string; // 음성안내용 요약 문장
}

/** 프로필별 가중치(합 = 1) */
export type ProfileWeights = Record<ProfileId, ScoreComponents>;

/** 점수화 옵션(음성/버튼으로 토글되는 사용자 조건) */
export interface ScoringOptions {
  /** 저상버스 우선 모드 */
  lowFloorPriority?: boolean;
  /** 날씨 회피 모드(날씨 위험 가중 강화) */
  weatherAvoid?: boolean;
  /** 계단 회피·승강기 우선 모드(접근성/승강기 가중 강화) */
  avoidStairs?: boolean;
}

/** 채점된 경로(후보 + 점수 결합) */
export interface ScoredRoute {
  route: RouteCandidate;
  score: RouteScore;
}
