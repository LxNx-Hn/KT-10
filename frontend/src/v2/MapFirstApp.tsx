import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
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
  SLOPE_LEGEND_BANDS,
} from './utils/slopeLevel';
import BottomDrawer from './components/BottomDrawer';
import MapControls from './components/MapControls';
import RouteDetailSheet, {
  type DetailTab,
} from './components/RouteDetailSheet';
import RouteResultsSheet from './components/RouteResultsSheet';
import type { RouteSheetSnap } from './routeSheetSnap';
import { sheetSnapLayoutFitToken } from './routeSheetSnap';
import { useSettledSheetSnap } from './useSettledSheetSnap';
import SearchHeader from './components/SearchHeader';
import SettingsPanel from './components/SettingsPanel';
import {
  buildRouteViewModel,
} from './routeViewModel';
import './map-first.css';

type DrawerId = 'profile' | 'conditions' | 'details' | 'departure' | 'settings';

const SEARCH_ROUTE_PATH = '/search';
const SEARCH_ROUTE_STATE_KEY = 'mob06Search';
const SEARCH_ROUTE_RETURN_KEY = 'mob06ReturnTo';

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

function shadeUnavailableHint(shade: RouteCandidate['shade']): string {
  // status가 명시적 불가일 때만 calculationNote를 노출. 야간·날씨 등은 추측하지 않는다.
  if (shade?.status === 'not_daylight' || shade?.status === 'unavailable') {
    const note = shade.calculationNote?.trim();
    if (note) return note;
  }
  return '현재 경로에서는 그늘 정보를 표시할 수 없어요';
}

function VoiceIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v5a3 3 0 0 0 3 3z" />
      <path d="M19 11a1 1 0 1 0-2 0 5 5 0 0 1-10 0 1 1 0 1 0-2 0 7 7 0 0 0 6 6.93V21a1 1 0 1 0 2 0v-3.07A7 7 0 0 0 19 11z" />
    </svg>
  );
}

export default function MapFirstApp({
  voiceOpen = false,
}: {
  /** App이 소유한 VoiceChatDock open boolean. data-voice-open 연결용. */
  voiceOpen?: boolean;
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
  const requestListen = useVoiceChatStore((state) => state.requestListen);

  const [drawer, setDrawer] = useState<DrawerId | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>('route');
  const [sheetSnap, setSheetSnap] = useState<RouteSheetSnap>('expanded');
  const settledSheetSnap = useSettledSheetSnap(sheetSnap);
  // /search 직접 진입·브라우저 앞뒤 이동도 같은 검색 화면 상태를 사용한다.
  const [searchPanelExpanded, setSearchPanelExpanded] = useState(
    () => window.location.pathname === SEARCH_ROUTE_PATH,
  );
  const searchViewport = useVisualViewportRect(searchPanelExpanded);
  const [showFacilities, setShowFacilities] = useState(false);
  const [showShade, setShowShade] = useState(true);
  const [showSlope, setShowSlope] = useState(true);
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
  const selectedTerrainPeakText = (() => {
    if (selectedTerrain?.status !== 'estimated_90m') return null;
    const peak = resolvePeakSlopePercent(
      selectedTerrain.maxSlopePercent,
      selectedTerrain.minSlopePercent,
    );
    return peak === null ? null : formatSlopePercent(peak);
  })();
  const hasFacilityOverlay = Boolean(
    selectedItem?.route.segments.some(
      (segment) =>
        Boolean(segment.path && segment.path.length > 0) &&
        ((segment.mode === 'subway' && segment.hasElevator === true) ||
          (segment.mode === 'bus' && segment.isLowFloorBus === true)),
    ),
  );
  const facilityDisabledHint = hasFacilityOverlay
    ? ''
    : '표시할 편의시설 정보가 없어요';
  const shadeDisabledHint = hasShadeOverlay
    ? ''
    : shadeUnavailableHint(selectedShade);
  const slopeDisabledHint = hasSlopeOverlay
    ? ''
    : '경로 상세에서 경사 수치를 확인할 수 있어요';
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
    if (window.location.pathname !== SEARCH_ROUTE_PATH) {
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
    if (window.location.pathname === SEARCH_ROUTE_PATH) {
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
      ? selectedView.summary
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
      } as CSSProperties
    : undefined;

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

        <SearchHeader
          mode={searchPanelMode}
          origin={origin}
          destination={destination}
          originInputRef={originInputRef}
          destinationInputRef={destinationInputRef}
          loading={loading}
          searchHint={searchHint}
          error={error}
          profileLabel={profileTriggerLabel(profileMeta.label)}
          profileDrawerOpen={drawer === 'profile'}
          settingsDrawerOpen={drawer === 'settings'}
          situationConditions={SITUATION_CONDITIONS}
          routeOptionConditions={ROUTE_OPTION_CONDITIONS}
          optionState={options}
          largeUi={largeUi}
          activeConditionCount={activeConditionCount}
          summaryConditionCount={summaryConditionCount}
          conditionsDrawerOpen={drawer === 'conditions'}
          onExpand={expandSearchPanel}
          onCollapse={collapseSearchPanel}
          onSelectOrigin={setOrigin}
          onClearOrigin={() => setOrigin(null)}
          onSelectDestination={setDestination}
          onClearDestination={() => setDestination(null)}
          onSwap={swapPlaces}
          onSearch={() => void runRouteSearch()}
          onEditSearch={editSearchConditions}
          onOpenProfile={() => setDrawer('profile')}
          onOpenSettings={() => setDrawer('settings')}
          onToggleOption={setScoringOption}
          onToggleLargeUi={toggleLargeUi}
          onOpenConditions={() => setDrawer('conditions')}
        />

        <MapControls
          locating={locating}
          showLabeledControls={showLabeledControls}
          showFacilities={showFacilities}
          hasFacilityOverlay={hasFacilityOverlay}
          facilityDisabledHint={facilityDisabledHint}
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
            setShowShade((visible) => !visible);
          }}
          onToggleSlope={() => {
            if (!hasSlopeOverlay) return;
            setShowSlope((visible) => !visible);
          }}
          onMapInfoOpenChange={setMapInfoOpen}
        />

        {shadeLayerVisible &&
          selectedShade?.shadeRatio !== undefined && (
            <div className="map-first__map-legend" role="note">
              <strong>
                {selectedShade.estimateKind === 'lower_bound'
                  ? '확인된 건물 그늘 최소 '
                  : '건물 그늘 '}
                {Math.round(selectedShade.shadeRatio * 100)}%
              </strong>
              <span><i className="map-first__legend-dot map-first__legend-dot--shade" />그늘</span>
              <span><i className="map-first__legend-dot map-first__legend-dot--sun" />햇빛</span>
              {selectedShade.status === 'estimated_demo' && <em>건물 높이 반영</em>}
            </div>
          )}

        {slopeLayerVisible && selectedTerrainAvgText !== null && (
            <div className="map-first__map-legend map-first__map-legend--slope" role="note">
              <strong>
                도보 경사 {selectedTerrainAvgText}%
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
                      : '텍스트로 입력해 주세요'}
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
                <button
                  key={item.id}
                  type="button"
                  role="radio"
                  aria-checked={profile === item.id}
                  className={`map-first__profile-option${
                    profile === item.id
                      ? ' map-first__profile-option--selected'
                      : ''
                  }`}
                  onClick={() => {
                    setProfile(item.id);
                    closeDrawer();
                  }}
                >
                  <strong>{item.label}</strong>
                  <span>{item.description}</span>
                </button>
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
      </div>
    </main>
  );
}
