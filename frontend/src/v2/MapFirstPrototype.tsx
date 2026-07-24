import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type RefObject } from 'react';
import './map-first.css';
import KakaoMap, { type KakaoMapHandle } from './KakaoMap';
import { type LngLatTuple, type MapProfileId } from './mapDemoData';
import { useAppStore } from '@/store/appStore';
import { adapters } from '@/adapters';
import type { Place, ScoredRoute } from '@/types';

type MapSurfaceHandle = KakaoMapHandle;

type SheetSnap = 'collapsed' | 'expanded';

type ProfileRouteConfig = {
  id: MapProfileId;
  label: string;
  title: string;
  meta: string;
  badges: string[];
  description: string;
};

type SheetViewModel = {
  title: string;
  meta: string;
  description: string;
  badges: string[];
};

const PROFILE_ORDER: MapProfileId[] = [
  'general',
  'elderly',
  'child',
  'youth',
  'disabled',
  'pregnant',
];

/** Survives React StrictMode remount so demo OD + search run once per page load */
let demoSearchBootstrapped = false;

/** Loading / empty fallback copy — live sheet uses selected recommendation when available */
const PROFILE_ROUTES: Record<MapProfileId, ProfileRouteConfig> = {
  general: {
    id: 'general',
    label: '일반',
    title: '가장 빠른 균형 경로',
    meta: '13분 · 도보 280m · 환승 0회',
    badges: ['빠른 도착', '환승 없음', '날씨 양호'],
    description: '시간과 보행 부담을 균형 있게 고려했어요.',
  },
  elderly: {
    id: 'elderly',
    label: '고령자',
    title: '보행 부담이 적은 경로',
    meta: '17분 · 도보 220m · 환승 0회',
    badges: ['계단 없음', '승강기 이용', '쉼터 1곳'],
    description: '조금 더 걸리지만 계단과 긴 도보를 피했어요.',
  },
  child: {
    id: 'child',
    label: '아동',
    title: '안전한 횡단 우선 경로',
    meta: '18분 · 도보 300m · 환승 0회',
    badges: ['신호 횡단 2곳', '사고 위험 낮음', '복잡한 환승 없음'],
    description: '사고 위험 구간과 복잡한 횡단을 피해 안내해요.',
  },
  youth: {
    id: 'youth',
    label: '청소년',
    title: '빠르고 단순한 경로',
    meta: '14분 · 도보 260m · 환승 0회',
    badges: ['빠른 도착', '환승 없음', '단순한 이동'],
    description: '시간과 환승을 단순하게 맞춘 데모 안내예요.',
  },
  disabled: {
    id: 'disabled',
    label: '장애인',
    title: '이동 장벽 없는 경로',
    meta: '20분 · 도보 180m · 환승 0회',
    badges: ['계단 없음', '승강기 이용', '저상버스 가능'],
    description: '휠체어와 보행보조기구로 이동 가능한 구간을 우선했어요.',
  },
  pregnant: {
    id: 'pregnant',
    label: '임산부',
    title: '보행 부담을 줄인 경로',
    meta: '18분 · 도보 210m · 환승 0회',
    badges: ['계단 없음', '승강기 이용', '쉼터 1곳'],
    description: '긴 도보와 계단 부담을 줄인 데모 안내예요.',
  },
};

/** Short characteristic badges from real ScoredRoute fields (mirrors RouteCard signals) */
function buildRouteBadges(item: ScoredRoute, profile: MapProfileId): string[] {
  const { route, score } = item;
  const badges: string[] = [];

  if (route.transferCount === 0) badges.push('환승 없음');

  switch (score.lowFloorStatus) {
    case 'confirmed':
      badges.push('저상버스 확인됨');
      break;
    case 'regular':
      badges.push('일반버스');
      break;
    case 'unknown':
      badges.push('저상 여부 미확인');
      break;
    case 'none':
      break;
  }

  const elevatorScore = score.components.elevator;
  if (typeof elevatorScore === 'number') {
    if (elevatorScore >= 80) badges.push('승강기 양호');
    else if (elevatorScore < 50) badges.push('승강기 없음/계단');
  }

  const weatherRisk = score.display.weatherRisk;
  if (typeof weatherRisk === 'number') {
    if (weatherRisk >= 40) badges.push('날씨 위험 높음');
    else if (weatherRisk < 20) badges.push('날씨 위험 낮음');
  }

  const hasStairs = route.segments.some((s) => s.hasStairs === true);
  if (!hasStairs) badges.push('계단 없음');

  const priority = (label: string): number => {
    if (profile === 'disabled') {
      if (label.includes('계단') || label.includes('승강기') || label.includes('저상')) return 0;
      return 1;
    }
    if (profile === 'child') {
      if (label.includes('날씨') || label.includes('환승') || label.includes('계단')) return 0;
      return 1;
    }
    return 1;
  };

  return [...badges].sort((a, b) => priority(a) - priority(b)).slice(0, 4);
}

function sheetFromRecommendation(
  item: ScoredRoute,
  profileLabel: string,
  rank: number,
  profile: MapProfileId,
): SheetViewModel {
  const { route, score } = item;
  return {
    title: `${profileLabel} 맞춤 ${rank}순위`,
    meta: `${route.summary} · ${route.totalDurationMin}분 · 도보 ${route.totalWalkM}m · 환승 ${route.transferCount}회`,
    description:
      score.reasons.length > 0
        ? score.reasons.join(' ')
        : '균형 잡힌 일반 경로예요.',
    badges: buildRouteBadges(item, profile),
  };
}

function easyModeDefaultFor(profile: MapProfileId): boolean {
  return profile !== 'general';
}

function placeSubtitle(place: Place): string {
  const parts = [place.category, place.address].filter(
    (part): part is string => Boolean(part && part.trim()),
  );
  return parts.join(' · ');
}

type PlaceComboboxProps = {
  fieldId: string;
  label: string;
  place: Place | null;
  onSelectPlace: (place: Place) => void;
  onClearPlace: () => void;
  inputRef?: RefObject<HTMLInputElement>;
  onSelected?: () => void;
  closeSignal: number;
};

/** Mock place autocomplete — uses adapters.places.searchPlaces */
function PlaceCombobox({
  fieldId,
  label,
  place,
  onSelectPlace,
  onClearPlace,
  inputRef,
  onSelected,
  closeSignal,
}: PlaceComboboxProps) {
  const [text, setText] = useState(place?.name ?? '');
  const [results, setResults] = useState<Place[]>([]);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [searching, setSearching] = useState(false);
  const [empty, setEmpty] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const debounceRef = useRef<number | undefined>(undefined);
  const requestIdRef = useRef(0);
  const mountedRef = useRef(true);
  const listboxId = `${fieldId}-listbox`;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      window.clearTimeout(debounceRef.current);
    };
  }, []);

  useEffect(() => {
    setText(place?.name ?? '');
  }, [place]);

  useEffect(() => {
    setOpen(false);
    setActiveIndex(-1);
    setEmpty(false);
    setLocalError(null);
  }, [closeSignal]);

  const closeList = () => {
    setOpen(false);
    setActiveIndex(-1);
  };

  const applyPlace = (next: Place) => {
    onSelectPlace(next);
    setText(next.name);
    setResults([]);
    closeList();
    setEmpty(false);
    setLocalError(null);
    onSelected?.();
  };

  const runSearch = async (query: string) => {
    const trimmed = query.trim();
    if (!trimmed) {
      requestIdRef.current += 1;
      setResults([]);
      setOpen(false);
      setEmpty(false);
      setLocalError(null);
      setSearching(false);
      return;
    }

    const requestId = ++requestIdRef.current;
    setSearching(true);
    setLocalError(null);
    try {
      const found = await adapters.places.searchPlaces(trimmed);
      if (!mountedRef.current || requestId !== requestIdRef.current) return;
      setResults(found);
      setEmpty(found.length === 0);
      setOpen(true);
      setActiveIndex(found.length > 0 ? 0 : -1);
    } catch {
      if (!mountedRef.current || requestId !== requestIdRef.current) return;
      setResults([]);
      setEmpty(false);
      setLocalError('장소를 찾지 못했어요.');
      setOpen(true);
      setActiveIndex(-1);
    } finally {
      if (mountedRef.current && requestId === requestIdRef.current) {
        setSearching(false);
      }
    }
  };

  const onChange = (value: string) => {
    setText(value);
    if (place && value !== place.name) {
      onClearPlace();
    }
    window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      void runSearch(value);
    }, 200);
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') {
      if (open) {
        event.preventDefault();
        closeList();
      }
      return;
    }

    if (!open || (results.length === 0 && !empty && !localError)) return;

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      if (results.length === 0) return;
      setActiveIndex((prev) => (prev + 1) % results.length);
      return;
    }

    if (event.key === 'ArrowUp') {
      event.preventDefault();
      if (results.length === 0) return;
      setActiveIndex((prev) => (prev <= 0 ? results.length - 1 : prev - 1));
      return;
    }

    if (event.key === 'Enter') {
      if (activeIndex >= 0 && activeIndex < results.length) {
        event.preventDefault();
        applyPlace(results[activeIndex]);
      }
    }
  };

  const showList = open && (results.length > 0 || empty || localError !== null || searching);

  return (
    <div className="map-first__combobox">
      <div className="map-first__search-row">
        <span
          className={`map-first__search-dot map-first__search-dot--${
            fieldId.includes('origin') ? 'origin' : 'dest'
          }`}
          aria-hidden="true"
        />
        <label className="map-first__sr-only" htmlFor={fieldId}>
          {label}
        </label>
        <input
          ref={inputRef}
          id={fieldId}
          className="map-first__search-input"
          type="text"
          role="combobox"
          value={text}
          placeholder={`${label} 검색`}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={onKeyDown}
          onFocus={() => {
            if (results.length > 0 || empty || localError) setOpen(true);
          }}
          aria-label={label}
          aria-expanded={showList}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-activedescendant={
            activeIndex >= 0 && results[activeIndex]
              ? `${fieldId}-option-${results[activeIndex].id}`
              : undefined
          }
          autoComplete="off"
        />
      </div>

      {showList && (
        <div className="map-first__suggest" id={listboxId} role="listbox" aria-label={`${label} 검색 결과`}>
          {searching && (
            <p className="map-first__suggest-status" role="status">
              검색 중…
            </p>
          )}
          {localError && (
            <p className="map-first__suggest-status" role="status">
              {localError}
            </p>
          )}
          {!searching && !localError && empty && (
            <p className="map-first__suggest-status" role="status">
              검색 결과가 없어요
            </p>
          )}
          {results.map((item, index) => {
            const active = index === activeIndex;
            const subtitle = placeSubtitle(item);
            return (
              <button
                key={item.id}
                id={`${fieldId}-option-${item.id}`}
                type="button"
                role="option"
                aria-selected={active}
                className={`map-first__suggest-option${
                  active ? ' map-first__suggest-option--active' : ''
                }`}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => applyPlace(item)}
                onMouseEnter={() => setActiveIndex(index)}
              >
                <span className="map-first__suggest-name">{item.name}</span>
                {subtitle ? (
                  <span className="map-first__suggest-sub">{subtitle}</span>
                ) : null}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

/**
 * Map-first UI v2 — mock place search + top-3 recommendation picker.
 */
export default function MapFirstPrototype() {
  const profile = useAppStore((s) => s.profile);
  const storeOrigin = useAppStore((s) => s.origin);
  const storeDestination = useAppStore((s) => s.destination);
  const recommendations = useAppStore((s) => s.recommendations);
  const selectedRouteId = useAppStore((s) => s.selectedRouteId);
  const loading = useAppStore((s) => s.loading);
  const error = useAppStore((s) => s.error);
  const loadDemoOd = useAppStore((s) => s.loadDemoOd);
  const search = useAppStore((s) => s.search);
  const setProfile = useAppStore((s) => s.setProfile);
  const selectRoute = useAppStore((s) => s.selectRoute);
  const setOrigin = useAppStore((s) => s.setOrigin);
  const setDestination = useAppStore((s) => s.setDestination);

  const [profilePanelOpen, setProfilePanelOpen] = useState(false);
  const [reversed, setReversed] = useState(false);
  const [heavyBags, setHeavyBags] = useState(false);
  const [avoidStairs, setAvoidStairs] = useState(false);
  const [layersVisible, setLayersVisible] = useState(false);
  const [listening, setListening] = useState(false);
  const [sheetSnap, setSheetSnap] = useState<SheetSnap>('expanded');
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);
  const [searchHint, setSearchHint] = useState<string | null>(null);
  const [closeSignal, setCloseSignal] = useState(0);
  const [easyMode, setEasyMode] = useState(() => easyModeDefaultFor(profile));
  const [altRoutesOpen, setAltRoutesOpen] = useState(false);

  const mapRef = useRef<MapSurfaceHandle | null>(null);
  const originInputRef = useRef<HTMLInputElement>(null);
  const destinationInputRef = useRef<HTMLInputElement>(null);
  const prevProfileRef = useRef(profile);

  const profileFallback = PROFILE_ROUTES[profile];
  const sheetExpanded = sheetSnap === 'expanded';
  const showLabeledControls = easyMode || profile !== 'general';
  const compactAltRoutes = easyMode || profile === 'elderly';
  const voiceLabel =
    profile === 'elderly' ? '음성으로 검색' : profile === 'child' ? '말로 검색' : '음성 검색';

  const canSearch = Boolean(
    storeOrigin && storeDestination && storeOrigin.id !== storeDestination.id,
  );

  const visibleRecommendations = useMemo(
    () => recommendations.slice(0, 3),
    [recommendations],
  );

  const selectedRecommendation = useMemo(() => {
    if (visibleRecommendations.length === 0) return undefined;
    return (
      visibleRecommendations.find((r) => r.route.id === selectedRouteId) ??
      visibleRecommendations[0]
    );
  }, [visibleRecommendations, selectedRouteId]);

  const selectedRank = useMemo(() => {
    if (!selectedRecommendation) return 1;
    const index = visibleRecommendations.findIndex(
      (r) => r.route.id === selectedRecommendation.route.id,
    );
    return index >= 0 ? index + 1 : 1;
  }, [visibleRecommendations, selectedRecommendation]);

  const sheet = useMemo((): SheetViewModel => {
    if (!selectedRecommendation || loading) {
      return {
        title: profileFallback.title,
        meta: profileFallback.meta,
        description: profileFallback.description,
        badges: profileFallback.badges,
      };
    }
    return sheetFromRecommendation(
      selectedRecommendation,
      profileFallback.label,
      selectedRank,
      profile,
    );
  }, [selectedRecommendation, loading, profileFallback, selectedRank, profile]);

  const routeCoordinates = useMemo((): LngLatTuple[] | null => {
    const path = selectedRecommendation?.route.path;
    if (!path || path.length < 2) return null;
    return path.map((point) => [point.lng, point.lat] as LngLatTuple);
  }, [selectedRecommendation]);

  const situationPending = heavyBags || avoidStairs;

  // Reset easy-mode default when profile changes (user can toggle afterward)
  useEffect(() => {
    if (prevProfileRef.current === profile) return;
    prevProfileRef.current = profile;
    setEasyMode(easyModeDefaultFor(profile));
    setAltRoutesOpen(false);
  }, [profile]);

  // One-shot demo OD + mock search (StrictMode-safe via module flag)
  useEffect(() => {
    if (demoSearchBootstrapped) return;
    demoSearchBootstrapped = true;

    const run = async () => {
      try {
        const { origin, destination } = useAppStore.getState();
        if (!origin || !destination) {
          loadDemoOd();
        }
        await search();
        setReversed(false);
      } catch {
        // search() already sets store.error
      }
    };

    void run();
  }, [loadDemoOd, search]);

  // If selection falls outside top 3 after rescoring, snap to new #1
  useEffect(() => {
    if (loading || visibleRecommendations.length === 0) return;
    const stillVisible = visibleRecommendations.some(
      (r) => r.route.id === selectedRouteId,
    );
    if (!stillVisible) {
      selectRoute(visibleRecommendations[0].route.id);
    }
  }, [visibleRecommendations, selectedRouteId, loading, selectRoute]);

  useEffect(() => {
    if (!profilePanelOpen) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setProfilePanelOpen(false);
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [profilePanelOpen]);

  useEffect(() => {
    if (!toastMessage) return;
    const timer = window.setTimeout(() => setToastMessage(null), 2500);
    return () => window.clearTimeout(timer);
  }, [toastMessage]);

  const closeSuggestions = () => setCloseSignal((n) => n + 1);

  const selectProfile = (next: MapProfileId) => {
    setProfile(next);
    setProfilePanelOpen(false);
    const top = useAppStore.getState().recommendations[0];
    if (top) selectRoute(top.route.id);
  };

  const swapPlaces = () => {
    const nextOrigin = storeDestination;
    const nextDestination = storeOrigin;
    setOrigin(nextOrigin);
    setDestination(nextDestination);
    setReversed(false);
    setSearchHint(null);
    closeSuggestions();
  };

  const runRouteSearch = async () => {
    if (!storeOrigin || !storeDestination) {
      setSearchHint('출발지와 도착지를 선택해 주세요.');
      return;
    }
    if (storeOrigin.id === storeDestination.id) {
      setSearchHint('출발지와 도착지가 같아요. 다른 장소를 선택해 주세요.');
      return;
    }
    setSearchHint(null);
    closeSuggestions();
    try {
      await search();
      setReversed(false);
    } catch {
      // store.error already set by search()
    }
  };

  const toggleSheet = () => {
    setSheetSnap((prev) => (prev === 'expanded' ? 'collapsed' : 'expanded'));
  };

  const startGuide = () => {
    setToastMessage('경로 안내를 시작할 준비가 되었어요.');
  };

  const goToCurrentLocation = () => {
    // Map-only demo — do not mutate store origin/destination Places
    if (!navigator.geolocation) {
      mapRef.current?.flyToDemoOrigin();
      setToastMessage('위치 권한을 사용할 수 없어 데모 위치를 표시해요.');
      return;
    }

    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setLocating(false);
        const coords: LngLatTuple = [
          position.coords.longitude,
          position.coords.latitude,
        ];
        mapRef.current?.flyToUserLocation(coords);
      },
      () => {
        setLocating(false);
        mapRef.current?.flyToDemoOrigin();
        setToastMessage('위치 권한을 사용할 수 없어 데모 위치를 표시해요.');
      },
      {
        enableHighAccuracy: true,
        timeout: 10000,
        maximumAge: 0,
      },
    );
  };

  const showRankList = visibleRecommendations.length > 0 && !loading;

  const frameClassName = [
    'map-first__frame',
    easyMode ? 'map-first__frame--easy' : '',
    heavyBags ? 'map-first__frame--heavy' : '',
    showLabeledControls ? 'map-first__frame--labeled' : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div className="map-first">
      <div
        className={frameClassName}
        data-profile={profile}
        role="application"
        aria-label="교통약자 맞춤 경로 추천"
      >
        <KakaoMap
          ref={mapRef}
          profile={profile}
          showFacilities={layersVisible}
          reversed={reversed}
          routeCoordinates={routeCoordinates}
        />

        <div className="map-first__top">
          <div className="map-first__search">
            <div className="map-first__search-body">
              <PlaceCombobox
                fieldId="map-first-origin"
                label="출발지"
                place={storeOrigin}
                onSelectPlace={setOrigin}
                onClearPlace={() => setOrigin(null)}
                inputRef={originInputRef}
                onSelected={() => destinationInputRef.current?.focus()}
                closeSignal={closeSignal}
              />
              <div className="map-first__search-divider" />
              <PlaceCombobox
                fieldId="map-first-destination"
                label="도착지"
                place={storeDestination}
                onSelectPlace={setDestination}
                onClearPlace={() => setDestination(null)}
                inputRef={destinationInputRef}
                closeSignal={closeSignal}
              />
              <button
                type="button"
                className="map-first__search-swap"
                aria-label="출발지와 도착지 바꾸기"
                onClick={swapPlaces}
              >
                <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <path d="M7 7h11M7 7l3-3M7 7l3 3M17 17H6M17 17l-3-3M17 17l-3 3" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            </div>

            <button
              type="button"
              className="map-first__search-submit"
              onClick={() => void runRouteSearch()}
              disabled={loading || !canSearch}
              aria-label="경로 검색"
            >
              {loading ? '경로 찾는 중…' : '경로 검색'}
            </button>

            <p className="map-first__demo-hint">Mock 장소·추천 데이터로 동작 중입니다</p>
            {searchHint && (
              <p className="map-first__demo-hint" role="status">
                {searchHint}
              </p>
            )}
            {loading && (
              <p className="map-first__demo-hint" role="status">
                추천 경로 불러오는 중…
              </p>
            )}
            {error && (
              <p className="map-first__demo-hint" role="status">
                {error}
              </p>
            )}
          </div>

          <div className="map-first__context">
            <button
              type="button"
              className="map-first__profile"
              aria-label={`프로필 선택, 현재 ${profileFallback.label}`}
              aria-haspopup="dialog"
              aria-expanded={profilePanelOpen}
              onClick={() => setProfilePanelOpen(true)}
            >
              {profileFallback.label}
              <span className="map-first__profile-chevron" aria-hidden="true">
                ▾
              </span>
            </button>
            <button
              type="button"
              className={`map-first__chip${heavyBags ? ' map-first__chip--active' : ''}`}
              aria-label="이동 상황 짐 많음"
              aria-pressed={heavyBags}
              onClick={() => setHeavyBags((prev) => !prev)}
            >
              짐 많음
            </button>
            <button
              type="button"
              className={`map-first__chip${avoidStairs ? ' map-first__chip--active' : ''}`}
              aria-label="이동 상황 계단 회피"
              aria-pressed={avoidStairs}
              onClick={() => setAvoidStairs((prev) => !prev)}
            >
              계단 회피
            </button>
            <button
              type="button"
              className={`map-first__chip map-first__chip--easy${
                easyMode ? ' map-first__chip--active' : ''
              }`}
              aria-label="쉬운 화면"
              aria-pressed={easyMode}
              onClick={() => {
                setEasyMode((prev) => {
                  const next = !prev;
                  if (next) setAltRoutesOpen(false);
                  return next;
                });
              }}
            >
              쉬운 화면
            </button>
          </div>
          {easyMode && (
            <p className="map-first__easy-hint" role="status">
              큰 글씨와 큰 버튼을 사용해요
            </p>
          )}
          {heavyBags && (
            <p className="map-first__easy-hint" role="status">
              큰 버튼으로 표시 중
            </p>
          )}
          {situationPending && (
            <p className="map-first__easy-hint" role="status">
              이동 조건의 추천 점수 연결은 준비 중입니다
            </p>
          )}
        </div>

        <div className="map-first__fab-stack">
          <button
            type="button"
            className={`map-first__fab${locating ? ' map-first__fab--busy' : ''}${
              showLabeledControls ? ' map-first__fab--labeled' : ''
            }`}
            aria-label="내 위치"
            aria-busy={locating}
            disabled={locating}
            onClick={goToCurrentLocation}
          >
            {locating ? (
              <span className="map-first__fab-spinner" aria-hidden="true" />
            ) : (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <circle cx="12" cy="12" r="3" />
                <path d="M12 2v3M12 19v3M2 12h3M19 12h3" strokeLinecap="round" />
                <circle cx="12" cy="12" r="8" />
              </svg>
            )}
            {showLabeledControls && <span className="map-first__fab-label">내 위치</span>}
          </button>
          <button
            type="button"
            className={`map-first__fab${layersVisible ? ' map-first__fab--active' : ''}${
              showLabeledControls ? ' map-first__fab--labeled' : ''
            }`}
            aria-label="편의시설"
            aria-pressed={layersVisible}
            onClick={() => setLayersVisible((prev) => !prev)}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M12 2l9 5-9 5-9-5 9-5z" strokeLinejoin="round" />
              <path d="M3 12l9 5 9-5M3 17l9 5 9-5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            {showLabeledControls && <span className="map-first__fab-label">편의시설</span>}
          </button>
        </div>

        <div className="map-first__voice-wrap">
          {listening && <span className="map-first__voice-status">듣고 있어요</span>}
          <button
            type="button"
            className={`map-first__voice${listening ? ' map-first__voice--listening' : ''}${
              showLabeledControls ? ' map-first__voice--labeled' : ''
            }`}
            aria-label={listening ? '듣고 있어요' : voiceLabel}
            aria-pressed={listening}
            onClick={() => setListening((prev) => !prev)}
          >
            {listening ? (
              <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <rect x="6" y="6" width="12" height="12" rx="2" />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v5a3 3 0 0 0 3 3z" />
                <path d="M19 11a1 1 0 1 0-2 0 5 5 0 0 1-10 0 1 1 0 1 0-2 0 7 7 0 0 0 6 6.93V21a1 1 0 1 0 2 0v-3.07A7 7 0 0 0 19 11z" />
              </svg>
            )}
            {showLabeledControls && (
              <span className="map-first__voice-label">
                {listening ? '듣고 있어요' : voiceLabel}
              </span>
            )}
          </button>
        </div>

        <section
          className={`map-first__sheet map-first__sheet--${sheetSnap}`}
          aria-label="경로 결과"
        >
          <button
            type="button"
            className="map-first__sheet-toggle"
            aria-expanded={sheetExpanded}
            aria-label={sheetExpanded ? '경로 결과 접기' : '경로 결과 펼치기'}
            onClick={toggleSheet}
          >
            <span className="map-first__sheet-handle" aria-hidden="true">
              <span className="map-first__sheet-handle-bar" />
            </span>
            <span className="map-first__sheet-header">
              <h2 className="map-first__sheet-title">{sheet.title}</h2>
              <p className="map-first__sheet-meta">{sheet.meta}</p>
              {showLabeledControls && (
                <span className="map-first__sheet-expand-hint">
                  {sheetExpanded ? '자세히 접기' : '자세히 펼치기'}
                </span>
              )}
            </span>
          </button>

          {sheetExpanded && (
            <div className="map-first__sheet-body">
              {compactAltRoutes &&
                visibleRecommendations.length > 1 &&
                !loading && (
                  <button
                    type="button"
                    className="map-first__alt-toggle"
                    aria-expanded={altRoutesOpen}
                    onClick={() => setAltRoutesOpen((prev) => !prev)}
                  >
                    {altRoutesOpen ? '다른 경로 접기' : '다른 경로 보기'}
                  </button>
                )}

              {showRankList && (
                <div
                  className="map-first__rank-list"
                  role="radiogroup"
                  aria-label="추천 경로 상위 선택"
                >
                  {visibleRecommendations.map((item, index) => {
                    const rank = index + 1;
                    const selected = item.route.id === selectedRecommendation?.route.id;
                    if (compactAltRoutes && !altRoutesOpen && !selected) {
                      return null;
                    }
                    const { route } = item;
                    return (
                      <button
                        key={route.id}
                        type="button"
                        role="radio"
                        aria-checked={selected}
                        className={`map-first__rank-option${
                          selected ? ' map-first__rank-option--selected' : ''
                        }`}
                        onClick={() => selectRoute(route.id)}
                        aria-label={`${rank}순위 ${route.summary}, ${route.totalDurationMin}분, 도보 ${route.totalWalkM}미터, 환승 ${route.transferCount}회`}
                      >
                        <span className="map-first__rank-badge">{rank}순위</span>
                        <span className="map-first__rank-copy">
                          <span className="map-first__rank-summary">{route.summary}</span>
                          <span className="map-first__rank-meta">
                            {route.totalDurationMin}분 · 도보 {route.totalWalkM}m · 환승{' '}
                            {route.transferCount}회
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}

              <p className="map-first__sheet-desc">{sheet.description}</p>
              <div className="map-first__badges">
                {sheet.badges.map((badge, index) => (
                  <span
                    key={`${badge}-${index}`}
                    className={`map-first__badge${index === 0 ? ' map-first__badge--good' : ''}`}
                  >
                    {badge}
                  </span>
                ))}
              </div>
              <button
                type="button"
                className="map-first__sheet-cta"
                aria-label="이 경로로 안내 시작"
                onClick={startGuide}
              >
                이 경로로 안내
              </button>
            </div>
          )}
        </section>

        {profilePanelOpen && (
          <div className="map-first__profile-layer">
            <button
              type="button"
              className="map-first__profile-backdrop"
              aria-label="프로필 선택 닫기"
              onClick={() => setProfilePanelOpen(false)}
            />
            <div
              className="map-first__profile-panel"
              role="dialog"
              aria-modal="true"
              aria-label="프로필 선택"
            >
              <div className="map-first__sheet-handle" aria-hidden="true">
                <span className="map-first__sheet-handle-bar" />
              </div>
              <p className="map-first__profile-panel-title">프로필 선택</p>
              <div className="map-first__profile-options" role="radiogroup" aria-label="이동 프로필">
                {PROFILE_ORDER.map((id) => {
                  const option = PROFILE_ROUTES[id];
                  const selected = profile === id;
                  return (
                    <button
                      key={id}
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      className={`map-first__profile-option${
                        selected ? ' map-first__profile-option--selected' : ''
                      }`}
                      onClick={() => selectProfile(id)}
                    >
                      {option.label}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {toastMessage && (
          <div className="map-first__toast" role="status">
            {toastMessage}
          </div>
        )}
      </div>
    </div>
  );
}
