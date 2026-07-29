import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from 'react';
import { useVoiceChatStore } from '@/chat/voiceChatStore';
import BusArrivalCard from '@/components/BusArrivalCard';
import DepartureTimePicker, {
  formatDepartureButtonLabel,
} from '@/components/DepartureTimePicker';
import FacilityReport from '@/components/FacilityReport';
import InstallPrompt from '@/components/InstallPrompt';
import RouteConditions, {
  ROUTE_CONDITION_KEYS,
} from '@/components/RouteConditions';
import RouteFeedback from '@/components/RouteFeedback';
import WeatherWarning from '@/components/WeatherWarning';
import { PROFILE_LIST, PROFILES } from '@/config/profiles';
import {
  useAppStore,
  type ToggleableScoringOption,
} from '@/store/appStore';
import { serverRankedRecommendations } from '@/utils/routes';
import KakaoMap, { SLOPE_COLOR_RAMP } from './KakaoMap';
import BottomDrawer from './components/BottomDrawer';
import RouteDetails from './components/RouteDetails';
import RouteResultList from './components/RouteResultList';
import RouteSearchPanel from './components/RouteSearchPanel';
import SettingsPanel from './components/SettingsPanel';
import {
  buildRouteViewModel,
} from './routeViewModel';
import './map-first.css';

type DrawerId = 'profile' | 'conditions' | 'details' | 'departure' | 'settings';
type DetailTab = 'route' | 'environment' | 'feedback';

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

const DETAIL_TABS: Array<[DetailTab, string]> = [
  ['route', '경로'],
  ['environment', '날씨·버스'],
  ['feedback', '후기·신고'],
];

/** 트리거 표시용. 내부 profile id/서버 값은 바꾸지 않는다. */
function profileTriggerLabel(label: string): string {
  const display = label === '청소년' ? '청년' : label;
  return `${display} 프로필`;
}

function LocationIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v3M12 19v3M2 12h3M19 12h3" strokeLinecap="round" />
      <circle cx="12" cy="12" r="8" />
    </svg>
  );
}

function FacilityIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M12 2l9 5-9 5-9-5 9-5z" strokeLinejoin="round" />
      <path d="M3 12l9 5 9-5M3 17l9 5 9-5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function VoiceIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v5a3 3 0 0 0 3 3z" />
      <path d="M19 11a1 1 0 1 0-2 0 5 5 0 0 1-10 0 1 1 0 1 0-2 0 7 7 0 0 0 6 6.93V21a1 1 0 1 0 2 0v-3.07A7 7 0 0 0 19 11z" />
    </svg>
  );
}

function ClockIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8v5l3 2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function MapFirstApp() {
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
  const [sheetExpanded, setSheetExpanded] = useState(true);
  const [searchPanelExpanded, setSearchPanelExpanded] = useState(true);
  const [showFacilities, setShowFacilities] = useState(false);
  const [searchHint, setSearchHint] = useState<string | null>(null);
  const [facilityHint, setFacilityHint] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);
  const [departureIsNow, setDepartureIsNow] = useState(true);
  const [departureRefreshing, setDepartureRefreshing] = useState(false);
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
  const hasShadeOverlay = Boolean(
    selectedShade &&
      (selectedShade.status === 'estimated_demo' ||
        selectedShade.status === 'estimated_public') &&
      (selectedShade.shadowPolygons.length > 0 ||
        selectedShade.pathSegments.length > 0),
  );
  const selectedTerrain = selectedItem?.route.terrain;
  const hasFacilityInfo = Boolean(
    selectedItem?.route.segments.some(
      (segment) =>
        (segment.mode === 'subway' && segment.hasElevator === true) ||
        (segment.mode === 'bus' && segment.isLowFloorBus === true),
    ),
  );
  const hasFacilityOverlay = Boolean(
    selectedItem?.route.segments.some(
      (segment) =>
        Boolean(segment.path && segment.path.length > 0) &&
        ((segment.mode === 'subway' && segment.hasElevator === true) ||
          (segment.mode === 'bus' && segment.isLowFloorBus === true)),
    ),
  );
  const activeConditionCount = ROUTE_CONDITION_KEYS.filter(
    (key) => Boolean(options[key]),
  ).length;
  const summaryConditionCount =
    SITUATION_CONDITIONS.filter(({ key }) => Boolean(options[key])).length
    + ROUTE_OPTION_CONDITIONS.filter(({ key }) => Boolean(options[key])).length
    + activeConditionCount;
  const searchPanelMode =
    !searchPanelExpanded && ranked.length > 0 && origin && destination
      ? 'compact'
      : 'expanded';
  const showVoiceControl = drawer === null && !(ranked.length > 0 && sheetExpanded);
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
    setFacilityHint(null);
  }, [selectedRouteId]);

  useEffect(() => {
    if (ranked.length === 0) {
      setSearchPanelExpanded(true);
    }
  }, [ranked.length]);

  // 지연 정밀화 구조에서 2위 이하 후보의 estimated 대중교통 선형·shade
  // 없음은 정상 상태다. 시간 기반 전체 재추천(refreshEnrichment 타이머)은
  // 불필요한 전체 /recommend 재실행을 만들므로 두지 않는다.

  const closeDrawer = useCallback(() => setDrawer(null), []);

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
      setSearchPanelExpanded(true);
      return;
    }
    if (origin.id === destination.id) {
      setSearchHint('출발지와 도착지가 같습니다. 다른 장소를 선택해 주세요.');
      setSearchPanelExpanded(true);
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
      setSheetExpanded(true);
    }
    setSearchPanelExpanded(!searchSucceeded);
  };

  const editSearchConditions = () => {
    setSearchPanelExpanded(true);
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

  const handleFacilityLayerClick = () => {
    if (hasFacilityOverlay) {
      setFacilityHint(null);
      setShowFacilities((visible) => !visible);
      return;
    }
    if (hasFacilityInfo) {
      setFacilityHint(
        '시설 이용 정보는 경로 세부 카드 항목에서 확인할 수 있어요.',
      );
      return;
    }
    setFacilityHint('선택한 경로의 편의시설 정보를 안내해 드립니다.');
  };

  const handleDetailTabKeyDown = (
    event: ReactKeyboardEvent<HTMLButtonElement>,
    index: number,
  ) => {
    let nextIndex: number | null = null;
    if (event.key === 'ArrowRight') {
      nextIndex = (index + 1) % DETAIL_TABS.length;
    } else if (event.key === 'ArrowLeft') {
      nextIndex = (index - 1 + DETAIL_TABS.length) % DETAIL_TABS.length;
    } else if (event.key === 'Home') {
      nextIndex = 0;
    } else if (event.key === 'End') {
      nextIndex = DETAIL_TABS.length - 1;
    }
    if (nextIndex === null) return;
    event.preventDefault();
    const nextTab = DETAIL_TABS[nextIndex][0];
    setDetailTab(nextTab);
    window.requestAnimationFrame(() => {
      document.getElementById(`detail-tab-${nextTab}`)?.focus();
    });
  };

  const renderDetailContent = (tab: DetailTab): ReactNode => {
    if (tab === 'route') {
      return selectedItem ? (
        <RouteDetails
          item={selectedItem}
          rank={selectedIndex + 1}
          profile={profile}
          peers={ranked}
        />
      ) : (
        <p>먼저 경로를 검색해 주세요.</p>
      );
    }
    if (tab === 'environment') {
      return (
        <>
          <WeatherWarning />
          <BusArrivalCard />
        </>
      );
    }
    if (tab === 'feedback') {
      return selectedItem ? (
        <div className="map-first__feedback-tab">
          <RouteFeedback key={selectedRouteId ?? 'no-route'} />
          <FacilityReport />
        </div>
      ) : (
        <p>경로를 선택하면 이용 후기를 남길 수 있습니다.</p>
      );
    }
    return null;
  };

  const frameClass = [
    'map-first__frame',
    largeUi ? 'map-first__frame--easy' : '',
    options.carryLuggage ? 'map-first__frame--heavy' : '',
    showLabeledControls ? 'map-first__frame--labeled' : '',
    ranked.length > 0 ? 'map-first__frame--results' : '',
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
    ? `${selectedView.meta} · ${selectedView.scoreKindLabel} ${selectedView.score.rounded}점`
    : loading
      ? '경사·건물 그늘·이동 편의 정보를 확인하고 있습니다.'
      : '카카오 장소 검색 결과에서 실제 장소를 선택해 주세요.';
  const departureButtonLabel = formatDepartureButtonLabel(
    options.departureAt,
    departureIsNow,
  );

  return (
    <main className="map-first" id="main-content">
      <h1 className="map-first__sr-only">부산 접근성 길찾기</h1>
      <div className={frameClass} data-profile={profile}>
        <KakaoMap
          origin={origin}
          destination={destination}
          recommendations={ranked}
          selectedRouteId={selectedRouteId}
          onSelectRoute={selectRoute}
          showFacilities={showFacilities}
          layoutFitKey={`${searchPanelMode}|${
            sheetExpanded ? 'sheet-expanded' : 'sheet-collapsed'
          }|${drawer ?? 'none'}`}
        />

        <RouteSearchPanel
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

        <div className="map-first__fab-stack">
          <button
            type="button"
            className={`map-first__fab${locating ? ' map-first__fab--busy' : ''}${
              showLabeledControls ? ' map-first__fab--labeled' : ''
            }`}
            aria-label="현재 위치를 출발지로 사용"
            aria-busy={locating}
            disabled={locating}
            onClick={locate}
          >
            {locating ? (
              <span className="map-first__fab-spinner" aria-hidden="true" />
            ) : (
              <LocationIcon />
            )}
            {showLabeledControls && <span className="map-first__fab-label">내 위치</span>}
          </button>
          <button
            type="button"
            className={`map-first__fab${
              showFacilities && hasFacilityOverlay ? ' map-first__fab--active' : ''
            }${
              showLabeledControls ? ' map-first__fab--labeled' : ''
            }`}
            aria-label={
              hasFacilityOverlay
                ? '편의시설 오버레이'
                : hasFacilityInfo
                  ? '편의시설 오버레이, 위치 데이터 없음'
                  : '편의시설 오버레이 자료 없음'
            }
            aria-pressed={hasFacilityOverlay ? showFacilities : undefined}
            onClick={handleFacilityLayerClick}
          >
            <FacilityIcon />
            {showLabeledControls && <span className="map-first__fab-label">편의시설</span>}
          </button>
          {facilityHint && (
            <p className="map-first__fab-hint" role="status" aria-live="polite">
              {facilityHint}
            </p>
          )}
        </div>

        {hasShadeOverlay &&
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

        {selectedTerrain?.status === 'estimated_90m' &&
          selectedTerrain.avgSlopePercent !== undefined && (
            <div className="map-first__map-legend map-first__map-legend--slope" role="note">
              <strong>
                도보 경사 {selectedTerrain.avgSlopePercent.toFixed(1)}%
                {selectedTerrain.maxSlopePercent !== undefined &&
                  ` (최대 ${selectedTerrain.maxSlopePercent.toFixed(1)}%)`}
              </strong>
              {SLOPE_COLOR_RAMP.map((band, index) => (
                <span key={band.label}>
                  <i
                    className="map-first__legend-dot"
                    style={{ backgroundColor: band.color }}
                  />
                  {band.label}
                  {' '}
                  {Number.isFinite(band.max)
                    ? `≤${band.max}%`
                    : `>${SLOPE_COLOR_RAMP[index - 1]?.max ?? 0}%`}
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
              onClick={requestListen}
            >
              <VoiceIcon />
              {showLabeledControls && (
                <span className="map-first__voice-label">음성 검색</span>
              )}
            </button>
          </div>
        )}

        <section
          className={`map-first__sheet map-first__sheet--${
            sheetExpanded ? 'expanded' : 'collapsed'
          }${ranked.length === 0 ? ' map-first__sheet--empty' : ''}`}
          aria-label="경로 결과"
        >
          <div className="map-first__sheet-stack">
            <InstallPrompt />
            <button
              type="button"
              className="map-first__sheet-toggle"
              aria-expanded={sheetExpanded}
              aria-label={sheetExpanded ? '경로 결과 접기' : '경로 결과 펼치기'}
              onClick={() => setSheetExpanded((expanded) => !expanded)}
            >
            <span className="map-first__sheet-handle" aria-hidden="true">
              <span className="map-first__sheet-handle-bar" />
            </span>
            <span className="map-first__sheet-header">
              <span className="map-first__sheet-title">{sheetTitle}</span>
              <span className="map-first__sheet-meta">{sheetMeta}</span>
            </span>
          </button>

          {sheetExpanded && (
            <div className="map-first__sheet-body">
              {loading && <p className="map-first__empty-state" role="status">경로를 찾고 있어요…</p>}
              {!loading && ranked.length > 0 && (
                <>
                  <button
                    type="button"
                    className="map-first__departure-btn"
                    aria-haspopup="dialog"
                    aria-expanded={drawer === 'departure'}
                    disabled={loading}
                    onClick={() => setDrawer('departure')}
                  >
                    <span className="map-first__departure-btn-icon" aria-hidden="true">
                      <ClockIcon />
                    </span>
                    <span className="map-first__departure-btn-label">
                      {departureButtonLabel}
                    </span>
                    <span className="map-first__departure-btn-chevron" aria-hidden="true">
                      ▾
                    </span>
                  </button>
                  <RouteResultList
                    recommendations={ranked}
                    profile={profile}
                    selectedRouteId={selectedRouteId}
                    refiningRouteKeys={refiningRouteKeys}
                    onSelectRoute={selectRoute}
                    onDetails={openDetails}
                  />
                </>
              )}
              {!loading && ranked.length === 0 && (
                <div className="map-first__empty-state">
                  <strong>검색 전에는 경로 수치나 편의 특성을 표시하지 않습니다.</strong>
                  <p>출발지와 도착지를 선택하면 비교 가능한 경로만 보여드려요.</p>
                </div>
              )}
            </div>
          )}
          </div>
        </section>

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

        {drawer === 'details' && (
          <BottomDrawer
            drawerId="details-drawer"
            title="경로 상세 정보"
            onClose={closeDrawer}
            panelClassName="map-first__drawer-panel--details"
          >
            <div className="map-first__details-layout">
              <div className="map-first__tabs" role="tablist" aria-label="상세 정보 종류">
                {DETAIL_TABS.map(([id, label], index) => (
                  <button
                    key={id}
                    id={`detail-tab-${id}`}
                    type="button"
                    role="tab"
                    aria-selected={detailTab === id}
                    aria-controls={`detail-panel-${id}`}
                    tabIndex={detailTab === id ? 0 : -1}
                    className={detailTab === id ? 'map-first__tab--active' : ''}
                    onClick={() => setDetailTab(id)}
                    onKeyDown={(event) => handleDetailTabKeyDown(event, index)}
                  >
                    {label}
                  </button>
                ))}
              </div>

              <div className="map-first__details-panels">
                {DETAIL_TABS.map(([id]) => (
                  <div
                    key={id}
                    id={`detail-panel-${id}`}
                    className="map-first__tab-panel"
                    role="tabpanel"
                    aria-labelledby={`detail-tab-${id}`}
                    hidden={detailTab !== id}
                  >
                    {detailTab === id ? renderDetailContent(id) : null}
                  </div>
                ))}
              </div>
            </div>
          </BottomDrawer>
        )}
      </div>
    </main>
  );
}
