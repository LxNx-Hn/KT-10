import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import { routeRefinementKey } from '@/store/appStore';
import type { ProfileId, ScoredRoute } from '@/types';
import { preferredScrollBehavior } from '@/utils/motion';
import { serverRankedRecommendations } from '@/utils/routes';
import {
  ROUTE_SCORE_DISCLAIMER,
  buildRouteViewModel,
} from '../routeViewModel';
import RouteSummaryCard from './RouteSummaryCard';

export default function RouteCarousel({
  recommendations,
  profile,
  selectedRouteId,
  refiningRouteKeys,
  onSelectRoute,
  onDetails,
}: {
  recommendations: ScoredRoute[];
  profile: ProfileId;
  selectedRouteId: string | null;
  refiningRouteKeys: string[];
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
          {views.map(({ item, view }) => (
            <RouteSummaryCard
              key={view.routeId}
              view={view}
              selected={view.routeId === selectedRouteId}
              refining={Boolean(
                item.routeSetToken
                && refiningRouteKeys.includes(
                  routeRefinementKey(item.routeSetToken, view.routeId),
                )
              )}
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
