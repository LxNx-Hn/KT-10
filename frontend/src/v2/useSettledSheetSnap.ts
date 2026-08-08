import { useEffect, useRef, useState } from 'react';
import {
  sheetHeightTransitionWaitMs,
  type RouteSheetSnap,
} from './routeSheetSnap';

const SHEET_SELECTOR = '.map-first__results-sheet.map-first__sheet';

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * UI class에는 즉시 반영되는 sheetSnap과 달리,
 * 지도 fitBounds용으로는 height(·max-height) transition이 끝난 뒤의 snap만 반환한다.
 */
export function useSettledSheetSnap(sheetSnap: RouteSheetSnap): RouteSheetSnap {
  const [settledSnap, setSettledSnap] = useState<RouteSheetSnap>(sheetSnap);
  const generationRef = useRef(0);

  useEffect(() => {
    if (sheetSnap === settledSnap) return;

    const generation = generationRef.current + 1;
    generationRef.current = generation;
    let cancelled = false;
    let rafId = 0;
    let fallbackTimer = 0;

    const finalize = () => {
      if (cancelled || generationRef.current !== generation) return;
      setSettledSnap(sheetSnap);
    };

    const sheet = document.querySelector<HTMLElement>(SHEET_SELECTOR);
    if (!sheet) {
      rafId = window.requestAnimationFrame(() => {
        rafId = window.requestAnimationFrame(finalize);
      });
      return () => {
        cancelled = true;
        window.cancelAnimationFrame(rafId);
      };
    }

    const style = window.getComputedStyle(sheet);
    const waitMs = sheetHeightTransitionWaitMs(
      style.transitionDuration,
      style.transitionDelay,
      prefersReducedMotion(),
    );

    if (waitMs <= 0) {
      rafId = window.requestAnimationFrame(() => {
        rafId = window.requestAnimationFrame(finalize);
      });
      return () => {
        cancelled = true;
        window.cancelAnimationFrame(rafId);
      };
    }

    const onTransitionEnd = (event: TransitionEvent) => {
      if (event.target !== sheet) return;
      if (
        event.propertyName !== 'height'
        && event.propertyName !== 'max-height'
      ) {
        return;
      }
      sheet.removeEventListener('transitionend', onTransitionEnd);
      if (fallbackTimer) window.clearTimeout(fallbackTimer);
      finalize();
    };

    sheet.addEventListener('transitionend', onTransitionEnd);
    // computed duration·delay 기준; 이벤트 누락 대비 한 프레임 여유만 둔다.
    fallbackTimer = window.setTimeout(finalize, waitMs + 16);

    return () => {
      cancelled = true;
      sheet.removeEventListener('transitionend', onTransitionEnd);
      if (fallbackTimer) window.clearTimeout(fallbackTimer);
      window.cancelAnimationFrame(rafId);
    };
  }, [sheetSnap, settledSnap]);

  return settledSnap;
}
