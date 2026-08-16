import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
} from 'react';
import { useVoiceChatStore } from '@/chat/voiceChatStore';
import DepartureTimePicker, {
  formatDepartureButtonLabel,
} from '@/components/DepartureTimePicker';
import RouteConditions, {
  ROUTE_CONDITION_KEYS,
} from '@/components/RouteConditions';
import { PROFILE_LIST, PROFILES } from '@/config/profiles';
import {
  hasKtClimateShelterData,
} from '@/data/ktClimateShelters';
import { useVisualViewportRect } from '@/hooks/useVisualViewportRect';
import {
  useAppStore,
  type ToggleableScoringOption,
} from '@/store/appStore';
import type { RouteCandidate } from '@/types';
import { serverRankedRecommendations } from '@/utils/routes';
import { primeSpeechOutput } from '@/voice/synthesis';
import KakaoMap from './KakaoMap';
import {
  formatSlopePercent,
  resolvePeakSlopePercent,
  resolveSlopeLevel,
  SLOPE_LEGEND_BANDS,
  SLOPE_LEVEL_LABELS,
} from './utils/slopeLevel';
import { formatRouteTransitTitle } from './formatRouteTransitTitle';
import BottomDrawer from './components/BottomDrawer';
import MapControls from './components/MapControls';
import RouteDetailSheet, {
  type DetailTab,
} from './components/RouteDetailSheet';
import RouteResultsSheet from './components/RouteResultsSheet';
import type { RouteSheetSnap } from './routeSheetSnap';
import { sheetSnapLayoutFitToken } from './routeSheetSnap';
import { useSettledSheetSnap } from './useSettledSheetSnap';
import {
  INITIAL_MAP_LAYER_VISIBILITY,
  toggleMapDataLayer,
} from './utils/mapLayerVisibility';
import SearchHeader from './components/SearchHeader';
import SettingsPanel from './components/SettingsPanel';
import ProfileOptionCard from './components/ProfileOptionCard';
import {
  buildRouteViewModel,
} from './routeViewModel';
import VoiceChatDock from '@/components/VoiceChatDock';
import './map-first.css';

type DrawerId = 'profile' | 'conditions' | 'details' | 'departure' | 'settings';

const SEARCH_ROUTE_PATH = '/search';
const SEARCH_ROUTE_STATE_KEY = 'mob06Search';
const SEARCH_ROUTE_RETURN_KEY = 'mob06ReturnTo';
const MOBILE_HOME_QUERY = '(max-width: 479px)';

type SearchHistoryState = Record<string, unknown> & {
  [SEARCH_ROUTE_STATE_KEY]?: boolean;
  [SEARCH_ROUTE_RETURN_KEY]?: string;
};

function currentRelativeUrl(): string {
  return `${window.location.pathname}${window.location.search}${window.location.hash}`;
}

function safeSearchReturnUrl(state: SearchHistoryState | null): string {
  const candidate = state?.[SEARCH_ROUTE_RETURN_KEY];
  return (
    typeof candidate === 'string'
    && candidate.startsWith('/')
    && !candidate.startsWith('//')
  )
    ? candidate
    : '/';
}

function subscribeMobileHome(onChange: () => void): () => void {
  if (typeof window.matchMedia !== 'function') return () => undefined;
  const media = window.matchMedia(MOBILE_HOME_QUERY);
  if (typeof media.addEventListener === 'function') {
    media.addEventListener('change', onChange);
    return () => media.removeEventListener('change', onChange);
  }
  media.addListener(onChange);
  return () => media.removeListener(onChange);
}

function getMobileHomeSnapshot(): boolean {
  return (
    typeof window.matchMedia === 'function'
    && window.matchMedia(MOBILE_HOME_QUERY).matches
  );
}

function getMobileHomeServerSnapshot(): boolean {
  return false;
}

function usesMobileSearchRoute(): boolean {
  // matchMedia가 없는 테스트 환경은 기존 MOB-06 모바일 계약으로 처리한다.
  return (
    typeof window.matchMedia !== 'function'
    || window.matchMedia(MOBILE_HOME_QUERY).matches
  );
}

const SITUATION_CONDITIONS: Array<{
  key: ToggleableScoringOption;
  label: string;
}> = [
  { key: 'carryLuggage', label: '짐 많음' },
];

const ROUTE_OPTION_CONDITIONS: Array<{
  key: ToggleableScoringOption;
  label: string;
}> = [
  { key: 'avoidStairs', label: '계단 회피' },
];

/** 트리거 표시용. 내부 profile id/서버 값은 바꾸지 않는다. */
function profileTriggerLabel(label: string): string {
  const display = label === '청소년' ? '청년' : label;
  return `${display} 프로필`;
}

function hasValidLatLng(point: { lat?: number; lng?: number } | undefined): boolean {
  return (
    typeof point?.lat === 'number'
    && Number.isFinite(point.lat)
    && typeof point?.lng === 'number'
    && Number.isFinite(point.lng)
  );
}

/** 지도에 그릴 수 있는 shade geometry가 있는지 (점수·수치와 별개). */
function routeHasShadeOverlay(shade: RouteCandidate['shade']): boolean {
  if (!shade) return false;
  if (shade.status !== 'estimated_demo' && shade.status !== 'estimated_public') {
    return false;
  }
  const hasPolygon = shade.shadowPolygons.some(
    (polygon) => polygon.filter(hasValidLatLng).length >= 3,
  );
  const hasPath = shade.pathSegments.some(
    (segment) => hasValidLatLng(segment.start) && hasValidLatLng(segment.end),
  );
  return hasPolygon || hasPath;
}

/** 지도 경사색에 쓰는 slopeSegments geometry 존재 여부. */
function routeHasSlopeOverlay(terrain: RouteCandidate['terrain']): boolean {
  if (terrain?.status !== 'estimated_90m') return false;
  return (terrain.slopeSegments ?? []).some(
    (segment) =>
      hasValidLatLng(segment.start)
      && hasValidLatLng(segment.end)
      && typeof segment.slopePercent === 'number'
      && Number.isFinite(segment.slopePercent),
  );
}

const MAP_INFO_SEARCH_FIRST_HINT = '경로를 먼저 검색해 주세요.';
const MAP_INFO_LOAD_FAILED_HINT =
  '정보를 불러오지 못했어요. 다시 시도해 주세요.';

function shadeUnavailableHint(
  shade: RouteCandidate['shade'],
  hasSelectedRoute: boolean,
): string {
  if (!hasSelectedRoute) return MAP_INFO_SEARCH_FIRST_HINT;
  if (shade?.status === 'not_daylight') {
    return '그늘 정보는 낮 시간대에 제공해요.';
  }
  return MAP_INFO_LOAD_FAILED_HINT;
}

function VoiceIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v5a3 3 0 0 0 3 3z" />
      <path d="M19 11a1 1 0 1 0-2 0 5 5 0 0 1-10 0 1 1 0 1 0-2 0 7 7 0 0 0 6 6.93V21a1 1 0 1 0 2 0v-3.07A7 7 0 0 0 19 11z" />
    </svg>
  );
}

const SLOPE_BAND_FEEL = {
  gentle: '편안한 경사',
  moderate: '약간 힘들 수 있어요',
  steep: '이동에 주의하세요',
  'very-steep': '우회 경로를 권장해요',
} as const;

function MobileSlopeLegend({
  average,
  peak,
  gradeLabel,
}: {
  average: string;
  peak: string | null;
  gradeLabel: string | null;
}) {
  const [expanded, setExpanded] = useState(false);
  const detailsId = 'map-first-mobile-slope-details';
  const summary = gradeLabel
    ? `경사 ${average}% · ${gradeLabel}`
    : `경사 ${average}%`;

  return (
    <section
      className="map-first__map-legend map-first__map-legend--slope map-first__mobile-slope-legend"
      role="note"
      aria-label="도보 경사 안내"
      data-expanded={expanded ? 'true' : 'false'}
    >
      <button
        type="button"
        className="map-first__mobile-slope-toggle"
        aria-expanded={expanded}
        aria-controls={detailsId}
        aria-label={expanded ? '경사 안내 접기' : '경사 안내 펼치기'}
        onClick={() => setExpanded((current) => !current)}
      >
        <strong>{summary}</strong>
        <span aria-hidden="true">{expanded ? '접기' : '보기'}</span>
      </button>

      {expanded && (
        <div className="map-first__mobile-slope-details" id={detailsId}>
          <div className="map-first__mobile-slope-metrics">
            <span>
              <b>평균 {average}%</b>
              <small>도보 구간의 전반적인 기울기</small>
            </span>
            {peak !== null && (
              <span>
                <b>최대 {peak}%</b>
                <small>가장 가파른 구간의 기울기</small>
              </span>
            )}
          </div>
          <p>
            평균은 전체 도보 구간의 기울기이고, 최대는 이동 중 만나는 가장
            가파른 구간이에요.
          </p>
          <ul className="map-first__mobile-slope-bands" aria-label="경사 색상 단계">
            {SLOPE_LEGEND_BANDS.map((band) => (
              <li key={band.id}>
                <i
                  className={`map-first__legend-dot map-first__legend-dot--slope-${band.id}`}
                  style={{ backgroundColor: band.color }}
                  aria-hidden="true"
                />
                <span>
                  <b>{band.legendText}</b>
                  <small>{SLOPE_BAND_FEEL[band.id]}</small>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function MapHomeIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      aria-hidden="true"
    >
      <path
        d="M3 11.5 12 4l9 7.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M5.5 10.5V20h13v-9.5M9.5 20v-5h5v5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function MobileSearchIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      aria-hidden="true"
    >
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m16 16 4 4" strokeLinecap="round" />
    </svg>
  );
}

function MobileSettingsIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      aria-hidden="true"
    >
      <circle cx="12" cy="8" r="3.5" />
      <path
        d="M5.5 20c.6-4 2.8-6 6.5-6s5.9 2 6.5 6"
        strokeLinecap="round"
      />
    </svg>
  );
}

export default function MapFirstApp({
  voiceOpen = false,
  onVoiceOpenChange,
}: {
  /** App이 소유한 VoiceChatDock open boolean. data-voice-open 연결용. */
  voiceOpen?: boolean;
  onVoiceOpenChange?: (open: boolean) => void;
} = {}) {
  const profile = useAppStore((state) => state.profile);
  const origin = useAppStore((state) => state.origin);
  const destination = useAppStore((state) => state.destination);
  const options = useAppStore((state) => state.options);
  const recommendations = useAppStore((state) => state.recommendations);
  const selectedRouteId = useAppStore((state) => state.selectedRouteId);
  const refiningRouteKeys = useAppStore((state) => state.refiningRouteKeys);
  const invalidateTransitRefinements = useAppStore(
    (state) => state.invalidateTransitRefinements,
  );
  const loading = useAppStore((state) => state.loading);
  const error = useAppStore((state) => state.error);
  const largeUi = useAppStore((state) => state.largeUi);
  const setProfile = useAppStore((state) => state.setProfile);
  const setOrigin = useAppStore((state) => state.setOrigin);
  const setDestination = useAppStore((state) => state.setDestination);
  const setScoringOption = useAppStore((state) => state.setScoringOption);
  const setDepartureAt = useAppStore((state) => state.setDepartureAt);
  const toggleLargeUi = useAppStore((state) => state.toggleLargeUi);
  const clearError = useAppStore((state) => state.clearError);
  const selectRoute = useAppStore((state) => state.selectRoute);
  const useCurrentLocation = useAppStore((state) => state.useCurrentLocation);
  const search = useAppStore((state) => state.search);
  const voiceStatus = useVoiceChatStore((state) => state.status);
  const voiceInputError = useVoiceChatStore((state) => state.voiceInputError);
  const requestListen = useVoiceChatStore((state) => state.requestListen);
  const mobileHomeEnabled = useSyncExternalStore(
    subscribeMobileHome,
    getMobileHomeSnapshot,
    getMobileHomeServerSnapshot,
  );

  const [drawer, setDrawer] = useState<DrawerId | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>('route');
  const [sheetSnap, setSheetSnap] = useState<RouteSheetSnap>('expanded');
  const settledSheetSnap = useSettledSheetSnap(sheetSnap);
  // /search 직접 진입·브라우저 앞뒤 이동도 같은 검색 화면 상태를 사용한다.
  const [searchPanelExpanded, setSearchPanelExpanded] = useState(
    () => (
      usesMobileSearchRoute()
      && window.location.pathname === SEARCH_ROUTE_PATH
    ),
  );
  const searchViewport = useVisualViewportRect(searchPanelExpanded);
  const [showFacilities, setShowFacilities] = useState(false);
  // 기본은 이동수단 색. 경사·그늘은 상호 배타 분석 레이어.
  const [{ showShade, showSlope }, setMapLayerVisibility] = useState(
    INITIAL_MAP_LAYER_VISIBILITY,
  );
  const [searchHint, setSearchHint] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);
  const [departureIsNow, setDepartureIsNow] = useState(true);
  const [departureRefreshing, setDepartureRefreshing] = useState(false);
  const [mapInfoOpen, setMapInfoOpen] = useState(false);
  const originInputRef = useRef<HTMLInputElement>(null);
  const destinationInputRef = useRef<HTMLInputElement>(null);
  const locatingTimerRef = useRef<number>();

  const ranked = useMemo(
    () => serverRankedRecommendations(recommendations),
    [recommendations],
  );
  const selectedIndex = ranked.findIndex(
    ({ route }) => route.id === selectedRouteId,
  );
  const selectedItem = selectedIndex >= 0 ? ranked[selectedIndex] : undefined;
  const selectedView = selectedItem
    ? buildRouteViewModel(selectedItem, selectedIndex + 1, profile)
    : null;
  const selectedShade = selectedItem?.route.shade;
  const hasShadeOverlay = routeHasShadeOverlay(selectedShade);
  const selectedTerrain = selectedItem?.route.terrain;
  const hasSlopeOverlay = routeHasSlopeOverlay(selectedTerrain);
  const selectedTerrainAvgText =
    selectedTerrain?.status === 'estimated_90m'
      ? formatSlopePercent(selectedTerrain.avgSlopePercent)
      : null;
  const selectedTerrainGradeLabel = (() => {
    if (selectedTerrain?.status !== 'estimated_90m') return null;
    const level = resolveSlopeLevel(selectedTerrain.avgSlopePercent);
    return level ? SLOPE_LEVEL_LABELS[level] : null;
  })();
  const selectedTerrainPeakText = (() => {
    if (selectedTerrain?.status !== 'estimated_90m') return null;
    const peak = resolvePeakSlopePercent(
      selectedTerrain.maxSlopePercent,
      selectedTerrain.minSlopePercent,
    );
    return peak === null ? null : formatSlopePercent(peak);
  })();
  const hasRouteFacilityOverlay = Boolean(
    selectedItem?.route.segments.some(
      (segment) =>
        Boolean(segment.path && segment.path.length > 0) &&
        ((segment.mode === 'subway' && segment.hasElevator === true) ||
          (segment.mode === 'bus' && segment.isLowFloorBus === true)),
    ),
  );
  const hasKtShelterOverlay = hasKtClimateShelterData();
  const hasFacilityOverlay = hasRouteFacilityOverlay || hasKtShelterOverlay;
  const facilityDisabledHint = hasFacilityOverlay
    ? ''
    : selectedItem
      ? '이 경로에는 표시할 편의시설이 없어요.'
      : MAP_INFO_SEARCH_FIRST_HINT;
  const facilityDetail = hasKtShelterOverlay
    ? 'KT 기후쉼터 · 승강기 · 저상버스'
    : undefined;
  const shadeDisabledHint = hasShadeOverlay
    ? ''
    : shadeUnavailableHint(selectedShade, Boolean(selectedItem));
  const slopeDisabledHint = hasSlopeOverlay
    ? ''
    : !selectedItem
      ? MAP_INFO_SEARCH_FIRST_HINT
      : selectedTerrain?.status === 'estimated_90m'
        ? '경로 상세에서 경사 수치를 확인할 수 있어요.'
        : MAP_INFO_LOAD_FAILED_HINT;
  const shadeLayerVisible = showShade && hasShadeOverlay;
  const slopeLayerVisible = showSlope && hasSlopeOverlay;
  const activeConditionCount = ROUTE_CONDITION_KEYS.filter(
    (key) => Boolean(options[key]),
  ).length;
  const summaryConditionCount =
    SITUATION_CONDITIONS.filter(({ key }) => Boolean(options[key])).length
    + ROUTE_OPTION_CONDITIONS.filter(({ key }) => Boolean(options[key])).length
    + activeConditionCount;
  // collapsed: 결과 없음 + 패널 닫힘
  // summary: 결과·OD 있음 + 패널 닫힘
  // expanded: 사용자가 검색창을 연 상태 (오류/빈 결과 포함)
  const searchPanelMode =
    searchPanelExpanded
      ? 'expanded'
      : ranked.length > 0 && origin && destination
        ? 'summary'
        : 'collapsed';
  const showVoiceControl = drawer === null && !(ranked.length > 0 && sheetSnap === 'expanded');
  const profileMeta = PROFILES[profile];
  const showLabeledControls =
    largeUi || profile === 'elderly' || profile === 'child' || profile === 'disabled';

  useEffect(
    () => () => {
      window.clearTimeout(locatingTimerRef.current);
    },
    [],
  );

  useEffect(
    () => () => invalidateTransitRefinements(),
    [invalidateTransitRefinements],
  );

  useEffect(() => {
    if (
      ranked.length > 0
      && !ranked.some(({ route }) => route.id === selectedRouteId)
    ) {
      selectRoute(ranked[0].route.id);
    }
  }, [ranked, selectRoute, selectedRouteId]);

  useEffect(() => {
    if (!locating) return;
    if (origin?.id === 'current' || error) {
      window.clearTimeout(locatingTimerRef.current);
      setLocating(false);
    }
  }, [error, locating, origin]);

  useEffect(() => {
    if (!hasFacilityOverlay && showFacilities) {
      setShowFacilities(false);
    }
  }, [hasFacilityOverlay, showFacilities]);

  useEffect(() => {
    const syncSearchRoute = () => {
      if (!usesMobileSearchRoute()) return;
      setSearchPanelExpanded(window.location.pathname === SEARCH_ROUTE_PATH);
    };
    window.addEventListener('popstate', syncSearchRoute);
    return () => window.removeEventListener('popstate', syncSearchRoute);
  }, []);

  useEffect(() => {
    if (!searchPanelExpanded) return;
    const frame = window.requestAnimationFrame(() => {
      if (!origin) originInputRef.current?.focus();
      else if (!destination) destinationInputRef.current?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [destination, origin, searchPanelExpanded]);

  // 그늘·경사가 없는 경로는 geometry가 없어 오버레이가 남지 않는다.
  // 사용자 ON/OFF 선호는 경로 변경 후에도 유지하고, 편의시설과 같이 가능 범위에서만 적용한다.

  // 지연 정밀화 구조에서 2위 이하 후보의 estimated 대중교통 선형·shade
  // 없음은 정상 상태다. 시간 기반 전체 재추천(refreshEnrichment 타이머)은
  // 불필요한 전체 /recommend 재실행을 만들므로 두지 않는다.
  // ranked.length === 0만으로 expanded를 강제하지 않는다(최초 진입은 collapsed).

  const closeDrawer = useCallback(() => setDrawer(null), []);

  const expandSearchPanel = () => {
    setDrawer(null);
    if (
      usesMobileSearchRoute()
      && window.location.pathname !== SEARCH_ROUTE_PATH
    ) {
      const previousState =
        window.history.state && typeof window.history.state === 'object'
          ? window.history.state as SearchHistoryState
          : {};
      window.history.pushState(
        {
          ...previousState,
          [SEARCH_ROUTE_STATE_KEY]: true,
          [SEARCH_ROUTE_RETURN_KEY]: currentRelativeUrl(),
        },
        '',
        SEARCH_ROUTE_PATH,
      );
    }
    setSearchPanelExpanded(true);
  };

  const collapseSearchPanel = () => {
    if (
      usesMobileSearchRoute()
      && window.location.pathname === SEARCH_ROUTE_PATH
    ) {
      const currentState =
        window.history.state && typeof window.history.state === 'object'
          ? window.history.state as SearchHistoryState
          : null;
      const nextState = currentState ? { ...currentState } : null;
      if (nextState) {
        delete nextState[SEARCH_ROUTE_STATE_KEY];
        delete nextState[SEARCH_ROUTE_RETURN_KEY];
      }
      window.history.replaceState(
        nextState && Object.keys(nextState).length > 0 ? nextState : null,
        '',
        safeSearchReturnUrl(currentState),
      );
    }
    setSearchPanelExpanded(false);
  };

  const swapPlaces = () => {
    const nextOrigin = destination;
    const nextDestination = origin;
    setOrigin(nextOrigin);
    setDestination(nextDestination);
    setSearchHint(null);
    if (!nextOrigin) originInputRef.current?.focus();
    else if (!nextDestination) destinationInputRef.current?.focus();
  };

  const runRouteSearch = async () => {
    if (!origin || !destination) {
      setSearchHint('검색 결과에서 출발지와 도착지를 모두 선택해 주세요.');
      expandSearchPanel();
      return;
    }
    if (origin.id === destination.id) {
      setSearchHint('출발지와 도착지가 같습니다. 다른 장소를 선택해 주세요.');
      expandSearchPanel();
      return;
    }
    setSearchHint(null);
    await search();
    // render closure의 ranked/recommendations가 아니라 store 최신 snapshot으로 판정한다.
    const latestState = useAppStore.getState();
    const searchSucceeded =
      latestState.recommendations.length > 0
      && latestState.error === null;
    if (searchSucceeded) {
      setSheetSnap('medium');
      collapseSearchPanel();
    } else {
      expandSearchPanel();
    }
  };

  const editSearchConditions = () => {
    expandSearchPanel();
  };

  const openMapHome = () => {
    collapseSearchPanel();
    setDrawer(null);
    if (ranked.length > 0) setSheetSnap('collapsed');
  };

  const openMobileSettings = () => {
    collapseSearchPanel();
    setDrawer('settings');
  };

  const locate = () => {
    if (locating) return;
    clearError();
    setLocating(true);
    useCurrentLocation();
    window.clearTimeout(locatingTimerRef.current);
    locatingTimerRef.current = window.setTimeout(() => setLocating(false), 10_500);
  };

  const openDetails = () => {
    setDetailTab('route');
    setDrawer('details');
  };

  const frameClass = [
    'map-first__frame',
    largeUi ? 'map-first__frame--easy' : '',
    showLabeledControls ? 'map-first__frame--labeled' : '',
    ranked.length > 0 ? 'map-first__frame--results' : '',
    searchPanelExpanded ? 'map-first__frame--search' : '',
  ]
    .filter(Boolean)
    .join(' ');

  const sheetTitle = loading
    ? '경로 찾는 중…'
    : selectedView
      ? formatRouteTransitTitle(selectedView.transitSteps, selectedView.summary)
      : error
        ? '경로를 표시하지 못했어요'
        : '출발지와 도착지를 검색하세요';
  const sheetMeta = selectedView
    ? `${selectedView.meta} · ${selectedView.score.summaryLabel}`
    : loading
      ? '경사·건물 그늘·이동 편의 정보를 확인하고 있습니다.'
      : '카카오 장소 검색 결과에서 실제 장소를 선택해 주세요.';
  const departureButtonLabel = formatDepartureButtonLabel(
    options.departureAt,
    departureIsNow,
  );
  const searchViewportStyle = searchPanelExpanded
    ? {
        '--mf-search-vv-width': `${searchViewport.width}px`,
        '--mf-search-vv-height': `${searchViewport.height}px`,
        '--mf-search-vv-offset-top': `${searchViewport.offsetTop}px`,
        '--mf-search-vv-offset-left': `${searchViewport.offsetLeft}px`,
        '--mf-search-vv-bottom-inset': `${searchViewport.bottomInset}px`,
      } as CSSProperties
    : undefined;
  const shadeLegend = shadeLayerVisible
    && selectedShade?.shadeRatio !== undefined && (
      <div className="map-first__map-legend" role="note">
        <strong>
          {selectedShade.estimateKind === 'lower_bound'
            ? '확인된 건물 그늘 최소 '
            : '건물 그늘 '}
          {Math.round(selectedShade.shadeRatio * 100)}%
        </strong>
        <span><i className="map-first__legend-dot map-first__legend-dot--shade" />회색 구역</span>
        {selectedShade.status === 'estimated_demo' && <em>건물 높이 반영</em>}
      </div>
    );
  const slopeLegend = slopeLayerVisible && selectedTerrainAvgText !== null
    ? mobileHomeEnabled
      ? (
          <MobileSlopeLegend
            key={selectedRouteId ?? 'selected-route'}
            average={selectedTerrainAvgText}
            peak={selectedTerrainPeakText}
            gradeLabel={selectedTerrainGradeLabel}
          />
        )
      : (
          <div className="map-first__map-legend map-first__map-legend--slope" role="note">
            <strong>
              {selectedTerrainGradeLabel
                ? `도보 경사 ${selectedTerrainAvgText}% · ${selectedTerrainGradeLabel}`
                : `도보 경사 ${selectedTerrainAvgText}%`}
              {selectedTerrainPeakText !== null
                ? ` (최대 ${selectedTerrainPeakText}%)`
                : ''}
            </strong>
            {SLOPE_LEGEND_BANDS.map((band) => (
              <span key={band.id}>
                <i
                  className={`map-first__legend-dot map-first__legend-dot--slope-${band.id}`}
                  style={{ backgroundColor: band.color }}
                  aria-hidden="true"
                />
                {band.legendText}
              </span>
            ))}
          </div>
        )
    : null;
  const mobileMapLegendsVisible =
    mobileHomeEnabled
    && drawer === null
    && !mapInfoOpen
    && !voiceOpen
    && !searchPanelExpanded
    && !(ranked.length > 0 && sheetSnap === 'expanded');

  const searchHeaderProps = {
    showMobileHome: mobileHomeEnabled,
    origin,
    destination,
    originInputRef,
    destinationInputRef,
    loading,
    searchHint,
    error,
    profileId: profile,
    profileLabel: profileTriggerLabel(profileMeta.label),
    profileDrawerOpen: drawer === 'profile',
    settingsDrawerOpen: drawer === 'settings',
    situationConditions: SITUATION_CONDITIONS,
    routeOptionConditions: ROUTE_OPTION_CONDITIONS,
    optionState: options,
    largeUi,
    activeConditionCount,
    summaryConditionCount,
    conditionsDrawerOpen: drawer === 'conditions',
    onExpand: expandSearchPanel,
    onCollapse: collapseSearchPanel,
    onSelectOrigin: setOrigin,
    onClearOrigin: () => setOrigin(null),
    onSelectDestination: setDestination,
    onClearDestination: () => setDestination(null),
    onSwap: swapPlaces,
    onSearch: () => void runRouteSearch(),
    onEditSearch: editSearchConditions,
    onOpenProfile: () => setDrawer('profile'),
    onOpenSettings: () => setDrawer('settings'),
    onToggleOption: setScoringOption,
    onToggleLargeUi: toggleLargeUi,
    onOpenConditions: () => setDrawer('conditions'),
  };

  return (
    <main
      className="map-first"
      id="main-content"
      style={searchViewportStyle}
      data-search-open={searchPanelExpanded ? 'true' : undefined}
      data-voice-open={voiceOpen ? 'true' : undefined}
      data-map-info-open={mapInfoOpen ? 'true' : undefined}
    >
      <h1 className="map-first__sr-only">부산 접근성 길찾기</h1>
      <div className={frameClass} data-profile={profile}>
        <KakaoMap
          origin={origin}
          destination={destination}
          recommendations={ranked}
          selectedRouteId={selectedRouteId}
          onSelectRoute={selectRoute}
          showFacilities={showFacilities}
          showShade={shadeLayerVisible}
          showSlope={slopeLayerVisible}
          layoutFitKey={`${searchPanelMode}|${sheetSnapLayoutFitToken(
            settledSheetSnap,
          )}|${drawer ?? 'none'}`}
        />

        {/* expanded 검색은 frame overflow clip 밖(.map-first__search-screen)에 둔다. */}
        {!searchPanelExpanded && (
          <SearchHeader mode={searchPanelMode} {...searchHeaderProps} />
        )}

        <MapControls
          locating={locating}
          showLabeledControls={showLabeledControls}
          showFacilities={showFacilities}
          hasFacilityOverlay={hasFacilityOverlay}
          facilityDisabledHint={facilityDisabledHint}
          facilityDetail={facilityDetail}
          showShade={showShade}
          hasShadeOverlay={hasShadeOverlay}
          shadeDisabledHint={shadeDisabledHint}
          showSlope={showSlope}
          hasSlopeOverlay={hasSlopeOverlay}
          slopeDisabledHint={slopeDisabledHint}
          onLocate={locate}
          onToggleFacilities={() => {
            if (!hasFacilityOverlay) return;
            setShowFacilities((visible) => !visible);
          }}
          onToggleShade={() => {
            if (!hasShadeOverlay) return;
            setMapLayerVisibility((current) => toggleMapDataLayer(current, 'shade'));
          }}
          onToggleSlope={() => {
            if (!hasSlopeOverlay) return;
            setMapLayerVisibility((current) => toggleMapDataLayer(current, 'slope'));
          }}
          onMapInfoOpenChange={setMapInfoOpen}
        />

        {mobileHomeEnabled
          ? mobileMapLegendsVisible && (shadeLegend || slopeLegend) && (
              <div
                className="map-first__mobile-map-legends"
                data-sheet-snap={sheetSnap}
              >
                {shadeLegend}
                {slopeLegend}
              </div>
            )
          : (
              <>
                {shadeLegend}
                {slopeLegend}
              </>
            )}

        {showVoiceControl && (
          <div className="map-first__voice-wrap">
            {voiceStatus !== 'idle' && (
              <span className="map-first__voice-status">
                {voiceStatus === 'listening'
                  ? '듣고 있어요'
                  : voiceStatus === 'thinking'
                    ? '분석 중'
                    : voiceStatus === 'speaking'
                      ? '안내 중'
                      : (voiceInputError ?? '텍스트로 입력해 주세요')}
              </span>
            )}
            <button
              type="button"
              className={`map-first__voice${
                voiceStatus === 'listening' ? ' map-first__voice--listening' : ''
              }${showLabeledControls ? ' map-first__voice--labeled' : ''}`}
              aria-label="음성 챗봇"
              aria-busy={voiceStatus === 'thinking'}
              disabled={
                voiceStatus === 'listening'
                || voiceStatus === 'thinking'
                || voiceStatus === 'speaking'
              }
              onClick={() => {
                primeSpeechOutput();
                requestListen();
              }}
            >
              <VoiceIcon />
              {showLabeledControls && (
                <span className="map-first__voice-label">음성 검색</span>
              )}
            </button>
          </div>
        )}

        <RouteResultsSheet
          sheetSnap={sheetSnap}
          loading={loading}
          ranked={ranked}
          profile={profile}
          selectedRouteId={selectedRouteId}
          refiningRouteKeys={refiningRouteKeys}
          sheetTitle={sheetTitle}
          sheetMeta={sheetMeta}
          departureButtonLabel={departureButtonLabel}
          departureDrawerOpen={drawer === 'departure'}
          onSheetSnapChange={setSheetSnap}
          onOpenDeparture={() => setDrawer('departure')}
          onSelectRoute={selectRoute}
          onDetails={openDetails}
        />

        <RouteDetailSheet
          open={drawer === 'details'}
          detailTab={detailTab}
          selectedItem={selectedItem}
          selectedIndex={selectedIndex}
          selectedRouteId={selectedRouteId}
          profile={profile}
          peers={ranked}
          onClose={closeDrawer}
          onDetailTabChange={setDetailTab}
        />

        {drawer === 'profile' && (
          <BottomDrawer
            drawerId="profile-drawer"
            title="이동 프로필 선택"
            onClose={closeDrawer}
          >
            <div
              className="map-first__profile-options"
              role="radiogroup"
              aria-label="이동 프로필"
            >
              {PROFILE_LIST.map((item) => (
                <ProfileOptionCard
                  key={item.id}
                  item={item}
                  selected={profile === item.id}
                  mobile={mobileHomeEnabled}
                  onSelect={(profileId) => {
                    setProfile(profileId);
                    closeDrawer();
                  }}
                />
              ))}
            </div>
          </BottomDrawer>
        )}

        {drawer === 'settings' && (
          <BottomDrawer
            drawerId="settings-drawer"
            title="내 설정"
            onClose={closeDrawer}
          >
            {mobileHomeEnabled && (
              <div className="map-first__mobile-personalization">
                <p className="map-first__mobile-personalization-intro">
                  프로필과 이번 이동 조건은 로그인 없이 바로 바꿀 수 있어요.
                  카카오 로그인은 설정 저장과 동기화에만 사용됩니다.
                </p>

                <section
                  className="map-first__mobile-settings-section"
                  aria-labelledby="mobile-settings-profile-title"
                >
                  <h3 id="mobile-settings-profile-title">이동 프로필</h3>
                  <div
                    className="map-first__profile-options"
                    role="radiogroup"
                    aria-label="내 설정 이동 프로필"
                  >
                    {PROFILE_LIST.map((item) => (
                      <ProfileOptionCard
                        key={item.id}
                        item={item}
                        selected={profile === item.id}
                        mobile
                        onSelect={setProfile}
                      />
                    ))}
                  </div>
                </section>

                <section
                  className="map-first__mobile-settings-section"
                >
                  <h3>이번 이동 조건</h3>
                  <p>지금 이동에 필요한 조건만 선택하세요.</p>
                  <div className="map-first__mobile-settings-quick-conditions">
                    {[...SITUATION_CONDITIONS, ...ROUTE_OPTION_CONDITIONS].map(
                      ({ key, label }) => {
                        const active = Boolean(options[key]);
                        return (
                          <button
                            key={key}
                            type="button"
                            className={`condition-chip${
                              active ? ' condition-chip--active' : ''
                            }`}
                            aria-pressed={active}
                            onClick={() => setScoringOption(key, !active)}
                          >
                            {label}
                          </button>
                        );
                      },
                    )}
                  </div>
                  <RouteConditions />
                </section>

                <h3 className="map-first__mobile-settings-account-title">
                  계정 및 화면
                </h3>
              </div>
            )}
            <SettingsPanel
              largeUi={largeUi}
              onToggleLargeUi={toggleLargeUi}
            />
          </BottomDrawer>
        )}

        {drawer === 'conditions' && (
          <BottomDrawer
            drawerId="conditions-drawer"
            title="이번 이동 조건"
            onClose={closeDrawer}
          >
            <RouteConditions />
          </BottomDrawer>
        )}

        {drawer === 'departure' && (
          <BottomDrawer
            drawerId="departure-drawer"
            title="출발 시간 설정"
            onClose={closeDrawer}
          >
            <DepartureTimePicker
              initialValue={options.departureAt}
              initialIsNow={departureIsNow}
              loading={loading || departureRefreshing}
              onCancel={closeDrawer}
              onApply={async (value, isNow) => {
                setDepartureRefreshing(true);
                try {
                  const refreshed = await setDepartureAt(value);
                  if (refreshed) {
                    setDepartureIsNow(isNow);
                    closeDrawer();
                  }
                } finally {
                  setDepartureRefreshing(false);
                }
              }}
            />
          </BottomDrawer>
        )}

        {mobileHomeEnabled && !searchPanelExpanded && (
          <nav className="map-first__mobile-nav" aria-label="주요 메뉴">
            <button
              type="button"
              className="map-first__mobile-nav-item"
              aria-label="지도 홈 메뉴"
              aria-current={drawer === null ? 'page' : undefined}
              onClick={openMapHome}
            >
              <MapHomeIcon />
              <span>지도 홈</span>
            </button>
            <button
              type="button"
              className="map-first__mobile-nav-item"
              aria-label="검색 메뉴"
              onClick={expandSearchPanel}
            >
              <MobileSearchIcon />
              <span>검색</span>
            </button>
            <button
              type="button"
              className="map-first__mobile-nav-item"
              aria-label="내 설정 메뉴"
              aria-current={drawer === 'settings' ? 'page' : undefined}
              onClick={openMobileSettings}
            >
              <MobileSettingsIcon />
              <span>내 설정</span>
            </button>
          </nav>
        )}

        {/* frame 내부 overlay — viewport fixed sibling이면 phone frame을 이탈한다 */}
        <VoiceChatDock
          variant="map-first"
          open={voiceOpen}
          onOpenChange={onVoiceOpenChange}
        />
      </div>

      {searchPanelExpanded && (
        <div
          className="map-first__search-screen"
          role="dialog"
          aria-modal="true"
          aria-label="경로 검색"
        >
          <SearchHeader mode="expanded" {...searchHeaderProps} />
        </div>
      )}
    </main>
  );
}
