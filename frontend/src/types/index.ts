/**
 * 도메인 핵심 타입 정의.
 * 점수화 엔진/어댑터/UI가 공유하는 단일 진실 공급원(SSOT).
 */

/* ───────────────────────── 프로필 ───────────────────────── */

export type ProfileId =
  | 'general'
  | 'elderly'
  | 'child'
  | 'youth'
  | 'disabled'
  | 'pregnant';

export interface ProfileMeta {
  id: ProfileId;
  label: string; // 화면 표시명
  description: string;
  /** 모바일 카드용 핵심 키워드(2개 권장). description 의미를 압축한 표시 전용 값. */
  keywords: string[];
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

  /* 버스 구간 속성 */
  busRouteName?: string;
  /** 저상버스 여부(미확인 = undefined) */
  isLowFloorBus?: Tristate;
  waitMin?: number; // 대기시간
  transitStartId?: string;
  transitEndId?: string;
  transitRouteId?: string;
  transitDirection?: string;
  transitDirectionCode?: 1 | 2;
  transitIntervalMin?: number;
  /** ODsay가 제공한 빠른 환승 승차 위치. 승강기 최적 위치가 아님. */
  fastBoardingPosition?: string;
  startExitNo?: string;
  endExitNo?: string;
  smartShelterName?: string;

  /* 역/수직이동(승강기) 속성 */
  stationName?: string;
  /** 승강기 이용 가능 여부(미확인 = undefined) */
  hasElevator?: Tristate;
  /** 수직이동(층 이동)이 필요한 구간인지 */
  needsVerticalMove?: boolean;
  path?: LatLng[];
  geometryQuality?: 'exact' | 'mixed' | 'estimated';
}

/** 카드 선택 시 서버가 반환하는 대중교통 표시 선형 정밀화 결과. */
export interface TransitRefinement {
  routeId: string;
  path: LatLng[];
  segments: RouteSegment[];
  geometryQuality: 'exact' | 'mixed' | 'estimated';
  refinedAt?: string;
}

export interface TransitLegArrival {
  segmentId: string;
  mode: 'bus' | 'subway';
  status: 'live' | 'scheduled' | 'unavailable';
  routeName?: string;
  boardingStopName?: string;
  direction?: string;
  arrivalMin?: number;
  arrivalMessage?: string;
  departureTime?: string;
  destinationArrivalTime?: string;
  observedAt: string;
  source: string;
}

export interface TransitArrivals {
  routeId: string;
  arrivals: TransitLegArrival[];
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
  /** 실제 경로/시설 데이터 공급자와 geometry 정확도 */
  sources?: string[];
  geometryQuality?: 'exact' | 'mixed' | 'estimated';
  terrain?: {
    avgSlopePercent?: number;
    maxSlopePercent?: number;
    minSlopePercent?: number;
    uphillDistanceM?: number;
    downhillDistanceM?: number;
    elevationGainM?: number;
    elevationLossM?: number;
    source?: string;
    resolutionM?: number;
    slopeSegments?: Array<{
      start: LatLng;
      end: LatLng;
      slopePercent: number;
      distanceM: number;
      /** 원본 보행 polyline을 따라가는 표시용 경로. 없으면 start/end 직선. */
      path?: LatLng[];
    }>;
    status: 'estimated_90m' | 'unavailable' | 'invalid';
  };
  shade?: {
    status: 'estimated_demo' | 'estimated_public' | 'not_daylight' | 'unavailable';
    evaluatedAt: string;
    shadeRatio?: number;
    shadedWalkM?: number;
    totalWalkM?: number;
    solarAzimuthDeg?: number;
    solarElevationDeg?: number;
    buildingHeightCoverage?: number;
    buildingCount?: number;
    knownHeightBuildingCount?: number;
    estimateKind?: 'estimate' | 'lower_bound';
    overlayResolutionM?: number;
    walkingGeometryQuality?: 'exact' | 'mixed' | 'estimated';
    includesTreeShade?: boolean;
    includesTerrainShadow?: boolean;
    source: string;
    dataQuality: 'demo' | 'public' | 'measured';
    shadowPolygons: LatLng[][];
    pathSegments: Array<{ start: LatLng; end: LatLng; shaded: boolean }>;
    calculationNote: string;
  };
  characteristics?: Array<
    | 'fastest'
    | 'shortest_walk'
    | 'lowest_slope'
    | 'most_shade'
    | 'fewest_transfers'
    | 'stair_free'
    | 'low_floor_confirmed'
  >;
  /** AI/규칙 라벨러가 근거와 함께 만든 경로 특성. unavailable은 장점 배지로 표시하지 않는다. */
  traitLabels?: Array<{
    labelId: string;
    displayLabel: string;
    evidenceStatus: 'observed' | 'derived' | 'unavailable';
    evidence: Array<{
      feature: string;
      value: string | number | boolean | null;
      unit?: string;
      source: string;
    }>;
  }>;
}

/* ───────────────────────── 날씨 ───────────────────────── */

export type AirQuality = 'good' | 'moderate' | 'bad' | 'very_bad';
export type SkyCondition = 'clear' | 'cloudy' | 'rain' | 'snow';

export interface WeatherCondition {
  label: string; // 시나리오 이름(예: "폭염")
  tempC: number;
  feelsLikeC: number; // 체감온도
  precipitationMm: number; // 강수
  isHeatwave?: boolean; // 공식 경보/시나리오에서 확인된 경우
  isColdwave?: boolean; // 공식 경보/시나리오에서 확인된 경우
  windMs: number; // 풍속
  pm10: number; // 미세먼지
  sky: SkyCondition;
  air: AirQuality;
}

/* ───────────────────────── 저상버스 도착 ───────────────────────── */

export interface BusArrival {
  routeName: string; // 예: "81"
  vehicleNo?: string;
  arrivalMin?: number; // 도착까지 분
  arrivalMessage?: string; // 예: "운행대기"
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
  accessibility?: number;
  walkComfort?: number;
  /** 지형 데이터가 확인된 경로에만 존재 */
  slopeComfort?: number;
  /** 주간 건물 그늘 비율이 확인된 경로에만 존재 */
  shadeComfort?: number;
  transferSimplicity?: number;
  elevator?: number;
  lowFloorBus?: number;
  weatherSafety?: number;
  safety?: number;
  dataReliability?: number;
  timeEfficiency?: number;
}

export type LowFloorStatus = 'confirmed' | 'regular' | 'unknown' | 'none';

export interface RouteScore {
  routeId: string;
  components: Partial<ScoreComponents>;
  /** 화면 표시용 파생값(높을수록 나쁨) */
  display: {
    walkBurden?: number;
    weatherRisk?: number;
  };
  finalScore: number; // 최종 추천 점수 0~100
  /** 점수 생성 근거. 누락된 구버전 응답은 rule_baseline으로 표시한다. */
  scoreKind?: 'rule_baseline' | 'bootstrap_baseline' | 'human_model';
  lowFloorStatus: LowFloorStatus;
  reasons: string[]; // 추천 이유
  cautions: string[]; // 주의사항
  voiceSummary: string; // 음성안내용 요약 문장
  /** 로그인 후기 저장 시 서버가 검증하는 서명된 추천 피처 스냅샷 */
  feedbackToken?: string;
}

/** 점수값은 미확인 피처를 생략할 수 있지만, 가중치 표에는 모든 키가 있어야 한다. */
export type ScoreWeights = Required<ScoreComponents>;

/** 프로필별 가중치(합 = 1) */
export type ProfileWeights = Record<ProfileId, ScoreWeights>;

/** 점수화 옵션(음성/버튼으로 토글되는 사용자 조건) */
export interface ScoringOptions {
  /** 짐이 많아 보행거리·계단·환승 부담을 크게 반영 */
  carryLuggage?: boolean;
  /** 유아차 이용: 단차·승강기·보행·저상버스 비중 강화 */
  stroller?: boolean;
  /** 저상버스 우선 모드 */
  lowFloorPriority?: boolean;
  /** 날씨 회피 모드(날씨 위험 가중 강화) */
  weatherAvoid?: boolean;
  /** 계단 회피·승강기 우선 모드(접근성/승강기 가중 강화) */
  avoidStairs?: boolean;
  /** 이번 경로검색에 ORS 휠체어 통행 제약을 강제 */
  usesWheelchair?: boolean;
  /** 확인된 건물 그늘 비율을 우선 반영 */
  shadePriority?: boolean;
  /** 환승 횟수가 적은 경로를 우선 반영 */
  minimizeTransfers?: boolean;
  /** 태양 위치와 그늘 계산 기준 시각(ISO 8601) */
  departureAt?: string;
}

/** 채점된 경로(후보 + 점수 결합) */
export interface ScoredRoute {
  route: RouteCandidate;
  score: RouteScore;
  /** 서버에 보관된 동일 후보군으로 시간별 그늘만 갱신할 때 사용하는 임시 토큰 */
  routeSetToken?: string;
}
