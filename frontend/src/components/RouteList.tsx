import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  type KeyboardEvent,
} from 'react';
import { useAppStore } from '@/store/appStore';
import { preferredScrollBehavior } from '@/utils/motion';
import { serverRankedRecommendations } from '@/utils/routes';
import RouteCard from './RouteCard';

/** 점수순 경로를 한 장씩 탐색하고, 활성 카드와 지도 선택 경로를 동기화한다. */
export default function RouteList() {
  const recommendations = useAppStore((state) => state.recommendations);
  const selectedRouteId = useAppStore((state) => state.selectedRouteId);
  const selectRoute = useAppStore((state) => state.selectRoute);
  const error = useAppStore((state) => state.error);
  const loading = useAppStore((state) => state.loading);
  const viewportRef = useRef<HTMLDivElement>(null);
  const scrollFrameRef = useRef<number>();
  const programmaticTargetRef = useRef<string | null>(null);
  const scrollReleaseRef = useRef<number>();

  const scrollCardIntoView = useCallback((
    routeId: string,
    behavior: ScrollBehavior,
  ) => {
    const target = Array.from(
      viewportRef.current?.querySelectorAll<HTMLElement>('[data-route-id]') ?? [],
    ).find((card) => card.dataset.routeId === routeId);
    if (!target) return;
    programmaticTargetRef.current = routeId;
    if (scrollReleaseRef.current !== undefined) {
      window.clearTimeout(scrollReleaseRef.current);
    }
    target.scrollIntoView?.({ behavior, block: 'nearest', inline: 'center' });
    scrollReleaseRef.current = window.setTimeout(() => {
      programmaticTargetRef.current = null;
    }, behavior === 'smooth' ? 500 : 0);
  }, []);

  const ranked = useMemo(
    () => serverRankedRecommendations(recommendations),
    [recommendations],
  );

  const activeIndex = Math.max(
    0,
    ranked.findIndex(({ route }) => route.id === selectedRouteId),
  );

  const moveTo = useCallback((
    index: number,
    behavior: ScrollBehavior = preferredScrollBehavior(),
  ) => {
    const targetIndex = Math.min(Math.max(index, 0), ranked.length - 1);
    const route = ranked[targetIndex];
    if (!route) return;
    selectRoute(route.route.id);
    scrollCardIntoView(route.route.id, behavior);
  }, [ranked, scrollCardIntoView, selectRoute]);

  useEffect(() => {
    if (!ranked.length) return;
    if (!selectedRouteId || !ranked.some(({ route }) => route.id === selectedRouteId)) {
      selectRoute(ranked[0].route.id);
      return;
    }
    if (programmaticTargetRef.current !== selectedRouteId) {
      scrollCardIntoView(selectedRouteId, preferredScrollBehavior());
    }
  }, [ranked, scrollCardIntoView, selectRoute, selectedRouteId]);

  useEffect(() => () => {
    if (scrollFrameRef.current !== undefined) cancelAnimationFrame(scrollFrameRef.current);
    if (scrollReleaseRef.current !== undefined) window.clearTimeout(scrollReleaseRef.current);
  }, []);

  const syncSelectionFromScroll = () => {
    if (programmaticTargetRef.current) {
      if (scrollReleaseRef.current !== undefined) {
        window.clearTimeout(scrollReleaseRef.current);
      }
      // 부드러운 이동이 끝날 때까지 중간 카드가 선택을 되돌리지 않게 한다.
      scrollReleaseRef.current = window.setTimeout(() => {
        programmaticTargetRef.current = null;
      }, 180);
      return;
    }
    if (scrollFrameRef.current !== undefined) cancelAnimationFrame(scrollFrameRef.current);
    scrollFrameRef.current = requestAnimationFrame(() => {
      const viewport = viewportRef.current;
      if (!viewport) return;
      const viewportCenter = viewport.getBoundingClientRect().left + viewport.clientWidth / 2;
      const cards = Array.from(viewport.querySelectorAll<HTMLElement>('[data-route-id]'));
      const nearest = cards.reduce<{ card: HTMLElement; distance: number } | null>((best, card) => {
        const rect = card.getBoundingClientRect();
        const distance = Math.abs(rect.left + rect.width / 2 - viewportCenter);
        return !best || distance < best.distance ? { card, distance } : best;
      }, null);
      const routeId = nearest?.card.dataset.routeId;
      if (routeId && routeId !== selectedRouteId) selectRoute(routeId);
    });
  };

  const handleKeyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (
      target !== event.currentTarget
      && !target.classList.contains('route-card')
    ) {
      return;
    }
    if (event.key === 'ArrowRight') {
      event.preventDefault();
      moveTo(activeIndex + 1);
    } else if (event.key === 'ArrowLeft') {
      event.preventDefault();
      moveTo(activeIndex - 1);
    } else if (event.key === 'Home') {
      event.preventDefault();
      moveTo(0);
    } else if (event.key === 'End') {
      event.preventDefault();
      moveTo(ranked.length - 1);
    }
  };

  if (error) return <p className="notice notice--error">{error}</p>;
  if (loading) return <p className="notice">경로를 평가하고 있어요…</p>;
  if (ranked.length === 0) {
    return (
      <p className="notice">
        출발지·도착지·프로필을 선택하고 <b>경로 찾기</b>를 눌러 주세요.
      </p>
    );
  }

  return (
    <section className="route-list" aria-label="적합 점수순 비교 경로">
      <div className="route-list__heading">
        <div>
          <h2 className="section-title">추천 경로 {ranked.length}개</h2>
          <p className="route-list__hint">
            프로필과 이번 이동 조건의 적합 점수순입니다. 좌우로 밀어 다른 길을 비교하세요.
          </p>
        </div>
        <output className="route-carousel__position" aria-live="polite">
          <strong>{activeIndex + 1}</strong> / {ranked.length}
        </output>
      </div>

      <div className="route-carousel">
        <button
          type="button"
          className="route-carousel__arrow route-carousel__arrow--prev"
          aria-label="이전 경로 보기"
          disabled={activeIndex === 0}
          onClick={() => moveTo(activeIndex - 1)}
        >
          ‹
        </button>
        <div
          ref={viewportRef}
          className="route-carousel__viewport"
          role="list"
          aria-label="점수순 경로 카드"
          tabIndex={0}
          onKeyDown={handleKeyboard}
          onScroll={syncSelectionFromScroll}
        >
          {ranked.map((item, index) => (
            <RouteCard key={item.route.id} item={item} rank={index + 1} />
          ))}
        </div>
        <button
          type="button"
          className="route-carousel__arrow route-carousel__arrow--next"
          aria-label="다음 경로 보기"
          disabled={activeIndex === ranked.length - 1}
          onClick={() => moveTo(activeIndex + 1)}
        >
          ›
        </button>
      </div>

      <div className="route-carousel__dots" aria-label="경로 바로 선택">
        {ranked.map(({ route }, index) => (
          <button
            key={route.id}
            type="button"
            className={`route-carousel__dot ${index === activeIndex ? 'route-carousel__dot--active' : ''}`}
            aria-label={`${index + 1}순위 경로 보기`}
            aria-current={index === activeIndex ? 'true' : undefined}
            onClick={() => moveTo(index)}
          />
        ))}
      </div>
      <p className="route-list__score-note">
        적합 점수는 후보 경로끼리 비교하기 위한 값이며 안전도나 성공 확률이 아닙니다.
      </p>
    </section>
  );
}
