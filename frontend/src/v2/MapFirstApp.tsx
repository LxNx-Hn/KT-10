import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
  type RefObject,
} from 'react';
import { adapters } from '@/adapters';
import { toUserMessage } from '@/api/http';
import { useVoiceChatStore } from '@/chat/voiceChatStore';
import BusArrivalCard from '@/components/BusArrivalCard';
import DepartureTimePicker, {
  formatDepartureButtonLabel,
} from '@/components/DepartureTimePicker';
import FacilityReport from '@/components/FacilityReport';
import KakaoLoginButton from '@/components/KakaoLoginButton';
import ProfilePreferences from '@/components/ProfilePreferences';
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
import type { Place, ProfileId, ScoredRoute } from '@/types';
import { preferredScrollBehavior } from '@/utils/motion';
import { serverRankedRecommendations } from '@/utils/routes';
import KakaoMap from './KakaoMap';
import {
  ROUTE_SCORE_DISCLAIMER,
  buildRouteViewModel,
  type V2RouteFactKind,
  type V2RouteViewModel,
} from './routeViewModel';
import './map-first.css';

type DrawerId = 'profile' | 'conditions' | 'details' | 'departure';
type DetailTab = 'route' | 'environment' | 'feedback' | 'settings';

const QUICK_CONDITIONS: Array<{
  key: ToggleableScoringOption;
  label: string;
}> = [
  { key: 'carryLuggage', label: '짐 많음' },
  { key: 'avoidStairs', label: '계단 회피' },
];

const DETAIL_TABS: Array<[DetailTab, string]> = [
  ['route', '경로'],
  ['environment', '날씨·버스'],
  ['feedback', '후기·신고'],
  ['settings', '내 설정'],
];

const FACT_KIND_LABEL: Record<V2RouteFactKind, string> = {
  advantage: '확인된 장점',
  caution: '주의',
  estimate: '추정',
  neutral: '정보',
  unknown: '확인 필요',
};

function placeSubtitle(place: Place): string {
  return [place.category, place.address]
    .filter((part): part is string => Boolean(part?.trim()))
    .join(' · ');
}

type PlaceComboboxProps = {
  fieldId: string;
  label: string;
  place: Place | null;
  onSelectPlace: (place: Place) => void;
  onClearPlace: () => void;
  inputRef?: RefObject<HTMLInputElement>;
  onSelected?: () => void;
};

/**
 * 카카오 장소 검색 어댑터를 사용하는 접근 가능한 자동완성 입력.
 * 입력 문자열과 실제로 선택된 Place를 분리해 좌표 없는 검색을 보내지 않는다.
 */
function PlaceCombobox({
  fieldId,
  label,
  place,
  onSelectPlace,
  onClearPlace,
  inputRef,
  onSelected,
}: PlaceComboboxProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const timeoutRef = useRef<number>();
  const requestIdRef = useRef(0);
  const mountedRef = useRef(true);
  const locallyClearingSelectionRef = useRef(false);
  const [text, setText] = useState(place?.name ?? '');
  const [results, setResults] = useState<Place[]>([]);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [searching, setSearching] = useState(false);
  const [empty, setEmpty] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const listboxId = `${fieldId}-listbox`;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestIdRef.current += 1;
      window.clearTimeout(timeoutRef.current);
    };
  }, []);

  useEffect(() => {
    if (locallyClearingSelectionRef.current && place === null) {
      locallyClearingSelectionRef.current = false;
      return;
    }
    requestIdRef.current += 1;
    window.clearTimeout(timeoutRef.current);
    setText(place?.name ?? '');
    setResults([]);
    setOpen(false);
    setActiveIndex(-1);
    setSearching(false);
    setEmpty(false);
    setLocalError(null);
  }, [place]);

  useEffect(() => {
    const closeFromOutside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
        setActiveIndex(-1);
      }
    };
    document.addEventListener('pointerdown', closeFromOutside);
    return () => document.removeEventListener('pointerdown', closeFromOutside);
  }, []);

  const closeList = () => {
    setOpen(false);
    setActiveIndex(-1);
  };

  const applyPlace = (next: Place) => {
    requestIdRef.current += 1;
    window.clearTimeout(timeoutRef.current);
    onSelectPlace(next);
    setText(next.name);
    setResults([]);
    setSearching(false);
    setEmpty(false);
    setLocalError(null);
    closeList();
    onSelected?.();
  };

  const searchPlaces = async (query: string, requestId: number) => {
    setSearching(true);
    setLocalError(null);
    try {
      const found = await adapters.places.searchPlaces(query);
      if (!mountedRef.current || requestId !== requestIdRef.current) return;
      setResults(found);
      setEmpty(found.length === 0);
      setActiveIndex(found.length > 0 ? 0 : -1);
      setOpen(true);
    } catch (error) {
      if (!mountedRef.current || requestId !== requestIdRef.current) return;
      setResults([]);
      setEmpty(false);
      setActiveIndex(-1);
      setLocalError(toUserMessage(error, '장소 검색에 실패했습니다.'));
      setOpen(true);
    } finally {
      if (mountedRef.current && requestId === requestIdRef.current) {
        setSearching(false);
      }
    }
  };

  const onChange = (value: string) => {
    const requestId = ++requestIdRef.current;
    window.clearTimeout(timeoutRef.current);
    setText(value);
    setSearching(false);
    setLocalError(null);
    setResults([]);
    setActiveIndex(-1);

    if (place && value !== place.name) {
      locallyClearingSelectionRef.current = true;
      onClearPlace();
    }

    const query = value.trim();
    if (query.length < 2) {
      setOpen(false);
      setEmpty(false);
      return;
    }

    setEmpty(false);
    timeoutRef.current = window.setTimeout(() => {
      void searchPlaces(query, requestId);
    }, 200);
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') {
      if (open) event.preventDefault();
      closeList();
      return;
    }
    if (!open || results.length === 0) return;

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActiveIndex((index) => (index + 1) % results.length);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveIndex((index) => (index <= 0 ? results.length - 1 : index - 1));
    } else if (event.key === 'Enter' && activeIndex >= 0) {
      event.preventDefault();
      applyPlace(results[activeIndex]);
    }
  };

  const showList =
    open && (searching || results.length > 0 || empty || localError !== null);

  return (
    <div className="map-first__combobox" ref={rootRef}>
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
          type="search"
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
          aria-busy={searching}
          aria-activedescendant={
            activeIndex >= 0 ? `${fieldId}-option-${activeIndex}` : undefined
          }
          autoComplete="off"
        />
      </div>

      {showList && (
        <div
          className="map-first__suggest"
          id={listboxId}
          role="listbox"
          aria-label={`${label} 검색 결과`}
        >
          {searching && (
            <p className="map-first__suggest-status" role="status">
              카카오 장소를 검색하는 중…
            </p>
          )}
          {localError && (
            <p className="map-first__suggest-status" role="alert">
              {localError}
            </p>
          )}
          {!searching && !localError && empty && (
            <p className="map-first__suggest-status" role="status">
              검색 결과가 없습니다. 다른 장소명이나 주소를 입력해 주세요.
            </p>
          )}
          {!searching &&
            results.map((item, index) => {
              const subtitle = placeSubtitle(item);
              const active = index === activeIndex;
              return (
                <button
                  key={`${item.id}-${index}`}
                  id={`${fieldId}-option-${index}`}
                  type="button"
                  role="option"
                  aria-selected={active}
                  className={`map-first__suggest-option${
                    active ? ' map-first__suggest-option--active' : ''
                  }`}
                  onPointerDown={(event) => event.preventDefault()}
                  onPointerEnter={() => setActiveIndex(index)}
                  onClick={() => applyPlace(item)}
                >
                  <span className="map-first__suggest-name">{item.name}</span>
                  {subtitle && (
                    <span className="map-first__suggest-sub">{subtitle}</span>
                  )}
                </button>
              );
            })}
        </div>
      )}
    </div>
  );
}

function BottomDrawer({
  drawerId,
  title,
  onClose,
  children,
}: {
  drawerId: string;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const previousFocus =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const focusTimer = window.setTimeout(() => {
      panelRef.current
        ?.querySelector<HTMLElement>('[data-autofocus], button, input, select')
        ?.focus();
    }, 0);

    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== 'Tab' || !panelRef.current) return;
      const focusable = Array.from(
        panelRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => !element.hidden);
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleKey);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener('keydown', handleKey);
      previousFocus?.focus();
    };
  }, [onClose]);

  return (
    <div className="map-first__drawer-layer">
      <button
        type="button"
        className="map-first__drawer-backdrop"
        aria-label={`${title} 닫기`}
        onClick={onClose}
      />
      <div
        ref={panelRef}
        className="map-first__drawer-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${drawerId}-title`}
      >
        <div className="map-first__sheet-handle" aria-hidden="true">
          <span className="map-first__sheet-handle-bar" />
        </div>
        <header className="map-first__drawer-head">
          <h2 id={`${drawerId}-title`}>{title}</h2>
          <button
            type="button"
            className="map-first__drawer-close"
            data-autofocus
            aria-label={`${title} 닫기`}
            onClick={onClose}
          >
            ×
          </button>
        </header>
        <div className="map-first__drawer-body">{children}</div>
      </div>
    </div>
  );
}

function RouteSummaryCard({
  view,
  selected,
  onSelect,
  onDetails,
}: {
  view: V2RouteViewModel;
  selected: boolean;
  onSelect: () => void;
  onDetails: () => void;
}) {
  const prioritizedFacts = [...view.facts].sort((left, right) => {
    const priority = (id: string) => {
      if (id === 'shade') return 0;
      if (id === 'terrain' || id === 'elevation-gain') return 1;
      if (id === 'stairs') return 2;
      if (id === 'elevator') return 3;
      return 4;
    };
    return priority(left.id) - priority(right.id);
  });
  const badgeCandidates: Array<{
    label: string;
    kind: V2RouteFactKind;
  }> = [
    ...prioritizedFacts.map((fact) => ({
      label: fact.label,
      kind: fact.kind,
    })),
    ...view.characteristicLabels.map((label) => ({
      label,
      kind: 'advantage' as const,
    })),
    ...view.traitLabels.map((label) => ({
      label,
      kind: 'advantage' as const,
    })),
  ];
  const badges = badgeCandidates.filter(
    (badge, index, all) =>
      all.findIndex((candidate) => candidate.label === badge.label) === index,
  );
  const shadeFact = view.facts.find((fact) => fact.id === 'shade');
  const shadeReason =
    shadeFact && (shadeFact.kind === 'unknown' || shadeFact.kind === 'neutral')
      ? shadeFact.detail
      : undefined;

  return (
    <article
      className={`map-first__route-card${
        selected ? ' map-first__route-card--selected' : ''
      }`}
      role="listitem"
      tabIndex={0}
      data-route-id={view.routeId}
      aria-current={selected ? 'true' : undefined}
      aria-label={`${view.rank}순위 경로, ${view.scoreKindLabel} ${view.score.rounded}점`}
      onClick={onSelect}
      onFocus={onSelect}
    >
      <header className="map-first__route-card-head">
        <span className="map-first__rank-badge">{view.rank}순위</span>
        <div className="map-first__route-card-title">
          <h3>{view.summary}</h3>
          <p>{view.title}</p>
        </div>
        <div className="map-first__route-score">
          <strong>{view.score.rounded}</strong>
          <span>/100</span>
          <small>{view.scoreKindLabel}</small>
        </div>
      </header>

      <ul className="map-first__route-stats" aria-label="경로 요약">
        <li>
          <strong>{view.stats.durationMin}</strong>
          <span>분</span>
        </li>
        <li>
          <strong>{view.stats.walkM}</strong>
          <span>m 도보</span>
        </li>
        <li>
          <strong>{view.stats.transferCount}</strong>
          <span>회 환승</span>
        </li>
      </ul>

      <div className="map-first__badges" aria-label="경로 사실 특성">
        {badges.slice(0, 4).map((badge) => (
          <span
            key={badge.label}
            className={`map-first__badge map-first__badge--${badge.kind}`}
          >
            {badge.label}
          </span>
        ))}
        {badges.length > 4 && (
          <span className="map-first__badge">특성 +{badges.length - 4}</span>
        )}
      </div>

      {shadeReason && (
        <p className="map-first__shade-reason">{shadeReason}</p>
      )}

      <button
        type="button"
        className="map-first__sheet-cta"
        onClick={(event) => {
          event.stopPropagation();
          onDetails();
        }}
      >
        상세 정보 보기
      </button>
    </article>
  );
}

function RouteCarousel({
  recommendations,
  profile,
  selectedRouteId,
  onSelectRoute,
  onDetails,
}: {
  recommendations: ScoredRoute[];
  profile: ProfileId;
  selectedRouteId: string | null;
  onSelectRoute: (routeId: string) => void;
  onDetails: () => void;
}) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const scrollFrameRef = useRef<number>();
  const programmaticTargetRef = useRef<string | null>(null);
  const ranked = useMemo(
    () => serverRankedRecommendations(recommendations),
    [recommendations],
  );
  const views = useMemo(
    () =>
      ranked.map((item, index) => ({
        item,
        view: buildRouteViewModel(item, index + 1, profile),
      })),
    [profile, ranked],
  );
  const selectedIndex = views.findIndex(
    ({ view }) => view.routeId === selectedRouteId,
  );
  const activeIndex = selectedIndex >= 0 ? selectedIndex : null;
  const orderKey = views.map(({ view }) => view.routeId).join('\u001f');
  const previousSelectionRef = useRef(selectedRouteId);
  const previousOrderRef = useRef(orderKey);

  const selectNearestVisibleCard = useCallback(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const center =
      viewport.getBoundingClientRect().left + viewport.clientWidth / 2;
    const cards = Array.from(
      viewport.querySelectorAll<HTMLElement>('[data-route-id]'),
    );
    const nearest = cards.reduce<{
      routeId: string;
      distance: number;
    } | null>((best, card) => {
      const rect = card.getBoundingClientRect();
      const distance = Math.abs(rect.left + rect.width / 2 - center);
      const routeId = card.dataset.routeId;
      if (!routeId || (best && best.distance <= distance)) return best;
      return { routeId, distance };
    }, null);
    if (nearest && nearest.routeId !== selectedRouteId) {
      onSelectRoute(nearest.routeId);
    }
  }, [onSelectRoute, selectedRouteId]);

  const scrollCardIntoView = useCallback(
    (routeId: string, behavior: ScrollBehavior) => {
      const viewport = viewportRef.current;
      const card = Array.from(
        viewportRef.current?.querySelectorAll<HTMLElement>('[data-route-id]') ??
          [],
      ).find((element) => element.dataset.routeId === routeId);
      if (!card || !viewport) return;
      programmaticTargetRef.current = routeId;
      const viewportRect = viewport.getBoundingClientRect();
      const cardRect = card.getBoundingClientRect();
      viewport.scrollTo?.({
        left:
          viewport.scrollLeft +
          cardRect.left -
          viewportRect.left -
          Math.max(0, (viewport.clientWidth - cardRect.width) / 2),
        behavior,
      });
    },
    [],
  );

  const moveTo = useCallback(
    (index: number) => {
      const targetIndex = Math.min(Math.max(index, 0), views.length - 1);
      const target = views[targetIndex]?.view;
      if (!target) return;
      onSelectRoute(target.routeId);
      scrollCardIntoView(target.routeId, preferredScrollBehavior());
    },
    [onSelectRoute, scrollCardIntoView, views],
  );

  useEffect(() => {
    const selectionChanged = previousSelectionRef.current !== selectedRouteId;
    const orderChanged = previousOrderRef.current !== orderKey;
    previousSelectionRef.current = selectedRouteId;
    previousOrderRef.current = orderKey;
    if (
      selectedRouteId
      && views.some(({ view }) => view.routeId === selectedRouteId)
      && (selectionChanged || orderChanged)
      && programmaticTargetRef.current !== selectedRouteId
    ) {
      scrollCardIntoView(selectedRouteId, preferredScrollBehavior());
    }
  }, [
    scrollCardIntoView,
    orderKey,
    selectedRouteId,
    views,
  ]);

  useEffect(
    () => () => {
      if (scrollFrameRef.current !== undefined) {
        cancelAnimationFrame(scrollFrameRef.current);
      }
    },
    [],
  );

  const syncSelectionFromScroll = () => {
    if (programmaticTargetRef.current) return;
    if (scrollFrameRef.current !== undefined) {
      cancelAnimationFrame(scrollFrameRef.current);
    }
    scrollFrameRef.current = requestAnimationFrame(() => {
      selectNearestVisibleCard();
    });
  };

  const beginUserScroll = () => {
    programmaticTargetRef.current = null;
  };

  const handleKeyboard = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'ArrowRight') {
      event.preventDefault();
      moveTo((activeIndex ?? -1) + 1);
    } else if (event.key === 'ArrowLeft') {
      event.preventDefault();
      moveTo((activeIndex ?? 1) - 1);
    } else if (event.key === 'Home') {
      event.preventDefault();
      moveTo(0);
    } else if (event.key === 'End') {
      event.preventDefault();
      moveTo(views.length - 1);
    }
  };

  return (
    <section className="map-first__route-list" aria-label="적합 점수순 비교 경로">
      <div className="map-first__route-list-heading">
        <div>
          <h2>추천 경로 {views.length}개</h2>
          <p>좌우로 밀어 다른 길의 특성과 적합 점수를 비교하세요.</p>
        </div>
        <output aria-live="polite">
          <strong>{activeIndex === null ? '–' : activeIndex + 1}</strong> / {views.length}
        </output>
      </div>

      <div className="map-first__route-carousel">
        <button
          type="button"
          className="map-first__route-arrow map-first__route-arrow--prev"
          aria-label="이전 경로 보기"
          disabled={activeIndex === null || activeIndex === 0}
          onClick={() => moveTo((activeIndex ?? 1) - 1)}
        >
          ‹
        </button>
        <div
          ref={viewportRef}
          className="map-first__route-viewport"
          role="list"
          aria-label="점수순 경로 카드"
          tabIndex={0}
          onKeyDown={handleKeyboard}
          onScroll={syncSelectionFromScroll}
          onPointerDown={beginUserScroll}
          onWheel={beginUserScroll}
        >
          {views.map(({ view }) => (
            <RouteSummaryCard
              key={view.routeId}
              view={view}
              selected={view.routeId === selectedRouteId}
              onSelect={() => onSelectRoute(view.routeId)}
              onDetails={() => {
                onSelectRoute(view.routeId);
                onDetails();
              }}
            />
          ))}
        </div>
        <button
          type="button"
          className="map-first__route-arrow map-first__route-arrow--next"
          aria-label="다음 경로 보기"
          disabled={activeIndex === null || activeIndex === views.length - 1}
          onClick={() => moveTo((activeIndex ?? -1) + 1)}
        >
          ›
        </button>
      </div>

      <div className="map-first__route-dots" aria-label="경로 바로 선택">
        {views.map(({ view }, index) => (
          <button
            key={view.routeId}
            type="button"
            aria-label={`${index + 1}순위 경로 보기`}
            aria-current={activeIndex !== null && index === activeIndex ? 'true' : undefined}
            className={
              activeIndex !== null && index === activeIndex
                ? 'map-first__route-dot map-first__route-dot--active'
                : 'map-first__route-dot'
            }
            onClick={() => moveTo(index)}
          />
        ))}
      </div>
      <p className="map-first__score-note">{ROUTE_SCORE_DISCLAIMER}</p>
    </section>
  );
}

function RouteDetails({
  item,
  rank,
  profile,
}: {
  item: ScoredRoute;
  rank: number;
  profile: ProfileId;
}) {
  const view = useMemo(
    () => buildRouteViewModel(item, rank, profile),
    [item, profile, rank],
  );
  const sources = item.route.sources ?? [];

  return (
    <section className="map-first__route-detail" aria-label="선택 경로 상세">
      <div className="map-first__route-detail-title">
        <div>
          <p>{view.title}</p>
          <h3>{view.summary}</h3>
        </div>
        <div className="map-first__route-score">
          <strong>{view.score.rounded}</strong>
          <span>/100</span>
        </div>
      </div>
      <p className="map-first__score-kind">{view.scoreKindLabel}</p>
      <p className="map-first__score-note">{ROUTE_SCORE_DISCLAIMER}</p>

      <dl className="map-first__fact-list">
        {view.facts.map((fact) => (
          <div key={`${fact.id}-${fact.label}`}>
            <dt>
              <span className={`map-first__fact-kind map-first__fact-kind--${fact.kind}`}>
                {FACT_KIND_LABEL[fact.kind]}
              </span>
              {fact.label}
            </dt>
            {fact.detail && <dd>{fact.detail}</dd>}
          </div>
        ))}
      </dl>

      {view.reasons.length > 0 && (
        <div className="map-first__detail-section">
          <h4>추천 이유</h4>
          <ul>{view.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
        </div>
      )}
      {view.cautions.length > 0 && (
        <div className="map-first__detail-section map-first__detail-section--warn">
          <h4>주의사항</h4>
          <ul>{view.cautions.map((caution) => <li key={caution}>{caution}</li>)}</ul>
        </div>
      )}
      {view.needsConfirmation.length > 0 && (
        <div className="map-first__detail-section">
          <h4>확인 필요한 정보</h4>
          <ul>
            {view.needsConfirmation.map((label) => <li key={label}>{label}</li>)}
          </ul>
        </div>
      )}
      <div className="map-first__detail-section">
        <h4>경로 데이터</h4>
        <p>
          지도 선 품질: {item.route.geometryQuality === 'exact'
            ? '실제 경로 형상'
            : item.route.geometryQuality === 'mixed'
              ? '주 경로·연결 경로 포함'
              : item.route.geometryQuality === 'estimated'
                ? '보행 연결 경로'
                : '공공 보행 경로'}
        </p>
        {sources.length > 0 ? (
          <ul>{sources.map((source) => <li key={source}>{source}</li>)}</ul>
        ) : (
          <p>공공 보행 경로망 데이터 기준</p>
        )}
      </div>
    </section>
  );
}

function SwapIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      aria-hidden="true"
    >
      <path
        d="M7 7h11M7 7l3-3M7 7l3 3M17 17H6M17 17l-3-3M17 17l-3 3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
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

function ShadeIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M4 20V8l8-4 8 4v12M8 20v-7h8v7" strokeLinejoin="round" />
      <path d="M3 20h18" strokeLinecap="round" />
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
  const refreshEnrichment = useAppStore((state) => state.refreshEnrichment);
  const voiceStatus = useVoiceChatStore((state) => state.status);
  const requestListen = useVoiceChatStore((state) => state.requestListen);

  const [drawer, setDrawer] = useState<DrawerId | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>('route');
  const [sheetExpanded, setSheetExpanded] = useState(true);
  const [showShade, setShowShade] = useState(true);
  const [showFacilities, setShowFacilities] = useState(false);
  const [searchHint, setSearchHint] = useState<string | null>(null);
  const [facilityHint, setFacilityHint] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);
  const [departureIsNow, setDepartureIsNow] = useState(true);
  const [departureRefreshing, setDepartureRefreshing] = useState(false);
  const originInputRef = useRef<HTMLInputElement>(null);
  const destinationInputRef = useRef<HTMLInputElement>(null);
  const locatingTimerRef = useRef<number>();
  const enrichmentRefreshRef = useRef({ odKey: '', attempt: 0 });

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
  const showVoiceControl = drawer === null && !(ranked.length > 0 && sheetExpanded);
  const dataSource = import.meta.env.VITE_DATA_SOURCE === 'mock' ? 'mock' : 'live';
  const profileMeta = PROFILES[profile];
  const showLabeledControls =
    largeUi || profile === 'elderly' || profile === 'child' || profile === 'disabled';

  useEffect(
    () => () => {
      window.clearTimeout(locatingTimerRef.current);
    },
    [],
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
    if (
      dataSource !== 'live'
      || !origin
      || !destination
      || !recommendations.length
      || recommendations.every(
        ({ route }) => (
          route.geometryQuality === 'exact'
          && route.terrain?.status === 'estimated_90m'
          && route.shade?.status !== 'unavailable'
        ),
      )
    ) {
      return undefined;
    }
    const odKey = `${origin.id}->${destination.id}`;
    if (enrichmentRefreshRef.current.odKey !== odKey) {
      enrichmentRefreshRef.current = { odKey, attempt: 0 };
    }
    const delays = [5_000, 10_000, 20_000, 30_000];
    const attempt = enrichmentRefreshRef.current.attempt;
    if (attempt >= delays.length) return undefined;
    const timer = window.setTimeout(() => {
      enrichmentRefreshRef.current.attempt += 1;
      void refreshEnrichment();
    }, delays[attempt]);
    return () => window.clearTimeout(timer);
  }, [
    dataSource,
    destination,
    origin,
    recommendations,
    refreshEnrichment,
  ]);

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
      return;
    }
    if (origin.id === destination.id) {
      setSearchHint('출발지와 도착지가 같습니다. 다른 장소를 선택해 주세요.');
      return;
    }
    setSearchHint(null);
    await search();
    if (useAppStore.getState().recommendations.length > 0) {
      setSheetExpanded(true);
    }
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
        <>
          <RouteFeedback key={selectedRouteId ?? 'no-route'} />
          <FacilityReport />
        </>
      ) : (
        <p>경로를 선택하면 이용 후기를 남길 수 있습니다.</p>
      );
    }
    return (
      <section className="map-first__settings" aria-label="로그인과 개인 설정">
        <KakaoLoginButton />
        <button
          type="button"
          className="map-first__settings-large"
          aria-pressed={largeUi}
          onClick={toggleLargeUi}
        >
          {largeUi ? '기본 글씨로 보기' : '큰 글씨와 큰 버튼 사용'}
        </button>
        <ProfilePreferences />
      </section>
    );
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
          showShade={showShade}
          showFacilities={showFacilities}
        />

        <div className="map-first__top">
          <div className="map-first__search">
            <div className="map-first__search-body">
              <PlaceCombobox
                fieldId="map-first-origin"
                label="출발지"
                place={origin}
                onSelectPlace={setOrigin}
                onClearPlace={() => setOrigin(null)}
                inputRef={originInputRef}
                onSelected={() => destinationInputRef.current?.focus()}
              />
              <div className="map-first__search-divider" />
              <PlaceCombobox
                fieldId="map-first-destination"
                label="도착지"
                place={destination}
                onSelectPlace={setDestination}
                onClearPlace={() => setDestination(null)}
                inputRef={destinationInputRef}
              />
              <button
                type="button"
                className="map-first__search-swap"
                aria-label="출발지와 도착지 바꾸기"
                onClick={swapPlaces}
              >
                <SwapIcon />
              </button>
            </div>

            <button
              type="button"
              className="map-first__search-submit"
              onClick={() => void runRouteSearch()}
              disabled={loading || !origin || !destination || origin.id === destination.id}
              aria-label="경로 찾기"
            >
              {loading ? '경로 찾는 중…' : '경로 찾기'}
            </button>

            {(searchHint || error) && (
              <p
                className={`map-first__search-message${
                  error ? ' map-first__search-message--error' : ''
                }`}
                role={error ? 'alert' : 'status'}
              >
                {searchHint ?? error}
              </p>
            )}
          </div>

          <div className="map-first__context">
            <button
              type="button"
              className="map-first__profile"
              aria-haspopup="dialog"
              aria-expanded={drawer === 'profile'}
              aria-label={`프로필 선택, 현재 ${profileMeta.label}`}
              onClick={() => setDrawer('profile')}
            >
              {profileMeta.label}
              <span className="map-first__profile-chevron" aria-hidden="true">▾</span>
            </button>
            {QUICK_CONDITIONS.map(({ key, label }) => {
              const active = Boolean(options[key]);
              return (
                <button
                  key={key}
                  type="button"
                  className={`map-first__chip${
                    active ? ' map-first__chip--active' : ''
                  }`}
                  aria-pressed={active}
                  onClick={() => setScoringOption(key, !active)}
                >
                  {label}
                </button>
              );
            })}
            <button
              type="button"
              className={`map-first__chip map-first__chip--easy${
                largeUi ? ' map-first__chip--active' : ''
              }`}
              aria-label="쉬운 화면"
              aria-pressed={largeUi}
              onClick={toggleLargeUi}
            >
              쉬운 화면
            </button>
            <button
              type="button"
              className="map-first__chip map-first__chip--conditions"
              aria-haspopup="dialog"
              aria-expanded={drawer === 'conditions'}
              aria-label={
                activeConditionCount > 0
                  ? `조건, 활성 ${activeConditionCount}개`
                  : '조건'
              }
              onClick={() => setDrawer('conditions')}
            >
              <span className="map-first__chip-label">조건</span>
              <span
                className={`map-first__condition-count${
                  activeConditionCount > 0
                    ? ''
                    : ' map-first__condition-count--empty'
                }`}
                aria-hidden="true"
              >
                {activeConditionCount > 0 ? activeConditionCount : 0}
              </span>
            </button>
          </div>
          {largeUi && (
            <p className="map-first__easy-hint" role="status">
              큰 글씨와 큰 버튼을 사용해요
            </p>
          )}
        </div>

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
          {hasShadeOverlay && (
            <button
              type="button"
              className={`map-first__fab${
                showShade ? ' map-first__fab--active' : ''
              }${
                showLabeledControls ? ' map-first__fab--labeled' : ''
              }`}
              aria-label="건물 그늘 오버레이"
              aria-pressed={showShade}
              onClick={() => setShowShade((visible) => !visible)}
            >
              <ShadeIcon />
              {showLabeledControls && <span className="map-first__fab-label">그늘</span>}
            </button>
          )}
          {facilityHint && (
            <p className="map-first__fab-hint" role="status" aria-live="polite">
              {facilityHint}
            </p>
          )}
        </div>

        {showShade &&
          hasShadeOverlay &&
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
              <span><i className="map-first__legend-dot map-first__legend-dot--slope-flat" />완만 ≤3%</span>
              <span><i className="map-first__legend-dot map-first__legend-dot--slope-moderate" />보통 ≤6%</span>
              <span><i className="map-first__legend-dot map-first__legend-dot--slope-steep" />급경사 ≤10%</span>
              <span><i className="map-first__legend-dot map-first__legend-dot--slope-danger" />위험 &gt;10%</span>
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
                  <RouteCarousel
                    recommendations={ranked}
                    profile={profile}
                    selectedRouteId={selectedRouteId}
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
          >
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
          </BottomDrawer>
        )}
      </div>
    </main>
  );
}
