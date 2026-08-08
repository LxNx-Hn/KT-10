import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
} from 'react';
import type { ProfileId, ScoredRoute } from '@/types';
import InstallPrompt from '@/components/InstallPrompt';
import CollapsedGuide from './CollapsedGuide';
import RouteResultList from './RouteResultList';
import {
  clampSheetSnapForResults,
  cycleSheetSnap,
  resolveBodyPointerIntent,
  resolveSheetSnapFromDrag,
  ROUTE_SHEET_DRAG,
  sheetSnapAriaExpanded,
  sheetSnapShowsBody,
  sheetSnapToggleLabel,
  type RouteSheetSnap,
} from '../routeSheetSnap';

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

export type RouteResultsSheetProps = {
  sheetSnap: RouteSheetSnap;
  loading: boolean;
  ranked: ScoredRoute[];
  profile: ProfileId;
  selectedRouteId: string | null;
  refiningRouteKeys: string[];
  sheetTitle: string;
  sheetMeta: string;
  departureButtonLabel: string;
  departureDrawerOpen: boolean;
  onSheetSnapChange: (snap: RouteSheetSnap) => void;
  onOpenDeparture: () => void;
  onSelectRoute: (routeId: string) => void;
  onDetails: () => void;
};

type DragSession = {
  pointerId: number;
  startY: number;
  startHeight: number;
  minHeight: number;
  maxHeight: number;
  lastY: number;
  lastTime: number;
  velocityY: number;
  moved: boolean;
};

type PendingBodyGesture = {
  pointerId: number;
  startY: number;
  scroller: HTMLElement;
};

/** CSS snap 클래스를 잠깐 적용해 렌더된 높이를 읽는다(수치 단일 기준=CSS). */
function measureSnapHeightPx(
  sheet: HTMLElement,
  snap: RouteSheetSnap,
  hasResults: boolean,
): number {
  const prevClass = sheet.className;
  const prevHeight = sheet.style.height;
  const prevMaxHeight = sheet.style.maxHeight;
  const prevTransition = sheet.style.transition;
  sheet.style.transition = 'none';
  sheet.style.height = '';
  sheet.style.maxHeight = '';
  const empty = hasResults ? '' : ' map-first__sheet--empty';
  sheet.className = `map-first__results-sheet map-first__sheet map-first__sheet--${snap}${empty}`;
  void sheet.offsetHeight;
  const height = sheet.getBoundingClientRect().height;
  sheet.className = prevClass;
  sheet.style.height = prevHeight;
  sheet.style.maxHeight = prevMaxHeight;
  // transition을 먼저 되돌리면 측정용 클래스 복원이 애니메되어 실측이 튀므로
  // 복원 reflow는 transition:none 상태에서 완료한 뒤 되돌린다.
  void sheet.offsetHeight;
  sheet.style.transition = prevTransition;
  return height;
}

export default function RouteResultsSheet({
  sheetSnap,
  loading,
  ranked,
  profile,
  selectedRouteId,
  refiningRouteKeys,
  sheetTitle,
  sheetMeta,
  departureButtonLabel,
  departureDrawerOpen,
  onSheetSnapChange,
  onOpenDeparture,
  onSelectRoute,
  onDetails,
}: RouteResultsSheetProps) {
  const sheetRef = useRef<HTMLElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<DragSession | null>(null);
  const pendingBodyRef = useRef<PendingBodyGesture | null>(null);
  /**
   * 유효 drag 직후 합성 pointer click(detail>0)만 1회 무시.
   * Enter/Space·보조기기(detail===0)는 무시하지 않는다.
   * 합성 click이 없으면 다음 pointerdown에서 잔여를 폐기한다.
   */
  const suppressPointerClickRef = useRef(false);
  const sheetSnapRef = useRef(sheetSnap);
  const hasResultsRef = useRef(ranked.length > 0);
  const onSnapRef = useRef(onSheetSnapChange);
  const listenersRef = useRef<{
    move: (event: PointerEvent) => void;
    up: (event: PointerEvent) => void;
    cancel: (event: PointerEvent) => void;
  } | null>(null);
  const pendingListenersRef = useRef<{
    move: (event: PointerEvent) => void;
    up: (event: PointerEvent) => void;
    cancel: (event: PointerEvent) => void;
  } | null>(null);
  const [dragHeightPx, setDragHeightPx] = useState<number | null>(null);
  const bodyId = useId();
  const hasResults = ranked.length > 0;
  const showBody = sheetSnapShowsBody(sheetSnap);

  sheetSnapRef.current = sheetSnap;
  hasResultsRef.current = hasResults;
  onSnapRef.current = onSheetSnapChange;

  useEffect(() => {
    const clamped = clampSheetSnapForResults(sheetSnap, hasResults);
    if (clamped !== sheetSnap) onSheetSnapChange(clamped);
  }, [hasResults, onSheetSnapChange, sheetSnap]);

  useEffect(
    () => () => {
      const listeners = listenersRef.current;
      if (listeners) {
        window.removeEventListener('pointermove', listeners.move);
        window.removeEventListener('pointerup', listeners.up);
        window.removeEventListener('pointercancel', listeners.cancel);
      }
      const pending = pendingListenersRef.current;
      if (pending) {
        window.removeEventListener('pointermove', pending.move);
        window.removeEventListener('pointerup', pending.up);
        window.removeEventListener('pointercancel', pending.cancel);
      }
    },
    [],
  );

  const detachDragListeners = () => {
    const listeners = listenersRef.current;
    if (!listeners) return;
    window.removeEventListener('pointermove', listeners.move);
    window.removeEventListener('pointerup', listeners.up);
    window.removeEventListener('pointercancel', listeners.cancel);
    listenersRef.current = null;
  };

  const detachPendingBodyListeners = () => {
    const listeners = pendingListenersRef.current;
    if (!listeners) return;
    window.removeEventListener('pointermove', listeners.move);
    window.removeEventListener('pointerup', listeners.up);
    window.removeEventListener('pointercancel', listeners.cancel);
    pendingListenersRef.current = null;
  };

  const clearPendingBody = () => {
    pendingBodyRef.current = null;
    detachPendingBodyListeners();
  };

  const endDrag = useCallback((cancel: boolean) => {
    const session = dragRef.current;
    dragRef.current = null;
    setDragHeightPx(null);
    detachDragListeners();
    if (!session || cancel) return;
    if (!session.moved) return;
    const deltaY = session.lastY - session.startY;
    const current = sheetSnapRef.current;
    const has = hasResultsRef.current;
    const next = clampSheetSnapForResults(
      resolveSheetSnapFromDrag({
        current,
        deltaY,
        velocityY: session.velocityY,
        hasResults: has,
      }),
      has,
    );
    if (
      next !== current
      || Math.abs(deltaY) >= ROUTE_SHEET_DRAG.flingMinDistance
    ) {
      suppressPointerClickRef.current = true;
    }
    if (next !== current) onSnapRef.current(next);
  }, []);

  const beginDrag = (
    event: Pick<PointerEvent, 'pointerId' | 'clientY' | 'timeStamp'> & {
      button?: number;
    },
    options?: {
      startY?: number;
      captureTarget?: Element | null;
    },
  ) => {
    if ((event.button ?? 0) !== 0) return;
    if (dragRef.current) return;
    clearPendingBody();
    const sheet = sheetRef.current;
    const has = hasResultsRef.current;
    const startHeight =
      dragHeightPx
      ?? sheet?.getBoundingClientRect().height
      ?? 0;
    // empty는 collapsed ↔ empty-expanded만 측정. medium(55%)을 경계에 넣지 않는다.
    const minHeight = sheet
      ? measureSnapHeightPx(sheet, 'collapsed', has)
      : startHeight;
    const maxHeight = sheet
      ? measureSnapHeightPx(sheet, 'expanded', has)
      : startHeight;
    const startY = options?.startY ?? event.clientY;
    dragRef.current = {
      pointerId: event.pointerId,
      startY,
      startHeight,
      minHeight,
      maxHeight: Math.max(minHeight, maxHeight),
      lastY: event.clientY,
      lastTime: event.timeStamp,
      velocityY: 0,
      moved: false,
    };

    const onPointerMove = (moveEvent: PointerEvent) => {
      const session = dragRef.current;
      if (!session || moveEvent.pointerId !== session.pointerId) return;
      const now = moveEvent.timeStamp;
      const dt = Math.max(16, now - session.lastTime);
      const dy = moveEvent.clientY - session.lastY;
      session.velocityY = dy / dt;
      session.lastY = moveEvent.clientY;
      session.lastTime = now;
      const deltaY = moveEvent.clientY - session.startY;
      if (Math.abs(deltaY) > 6) session.moved = true;
      const nextH = Math.min(
        session.maxHeight,
        Math.max(session.minHeight, session.startHeight - deltaY),
      );
      setDragHeightPx(nextH);
    };

    const onPointerUp = (upEvent: PointerEvent) => {
      const session = dragRef.current;
      if (!session || upEvent.pointerId !== session.pointerId) return;
      endDrag(false);
    };

    const onPointerCancel = (cancelEvent: PointerEvent) => {
      const session = dragRef.current;
      if (!session || cancelEvent.pointerId !== session.pointerId) return;
      endDrag(true);
    };

    listenersRef.current = {
      move: onPointerMove,
      up: onPointerUp,
      cancel: onPointerCancel,
    };
    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
    window.addEventListener('pointercancel', onPointerCancel);

    const captureTarget = options?.captureTarget;
    if (captureTarget && 'setPointerCapture' in captureTarget) {
      try {
        (captureTarget as HTMLElement).setPointerCapture(event.pointerId);
      } catch {
        /* optional */
      }
    }
  };

  const onTogglePointerDown = (event: ReactPointerEvent<HTMLButtonElement>) => {
    // 이전 sequence에서 합성 click이 오지 않았다면 잔여 suppress를 폐기.
    if (suppressPointerClickRef.current) {
      suppressPointerClickRef.current = false;
    }
    beginDrag(event, { captureTarget: event.currentTarget });
  };

  const onToggleClick = (event: ReactMouseEvent<HTMLButtonElement>) => {
    // 키보드·보조기기 활성화(detail===0)는 항상 허용.
    if (event.detail === 0) {
      suppressPointerClickRef.current = false;
      onSheetSnapChange(cycleSheetSnap(sheetSnap, hasResults));
      return;
    }
    // 같은 pointer sequence의 합성 click만 1회 무시.
    if (suppressPointerClickRef.current) {
      suppressPointerClickRef.current = false;
      return;
    }
    onSheetSnapChange(cycleSheetSnap(sheetSnap, hasResults));
  };

  const onBodyPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!showBody || !hasResults) return;
    if (event.button !== 0) return;
    if (dragRef.current || pendingBodyRef.current) return;
    const scroller = bodyRef.current?.querySelector(
      '.map-first__route-stack',
    ) as HTMLElement | null;
    if (!scroller) return;
    if (!scroller.contains(event.target as Node)) return;
    if (scroller.scrollTop > 0) return;

    pendingBodyRef.current = {
      pointerId: event.pointerId,
      startY: event.clientY,
      scroller,
    };

    const onPointerMove = (moveEvent: PointerEvent) => {
      const pending = pendingBodyRef.current;
      if (!pending || moveEvent.pointerId !== pending.pointerId) return;
      const intent = resolveBodyPointerIntent({
        scrollTop: pending.scroller.scrollTop,
        deltaY: moveEvent.clientY - pending.startY,
      });
      if (intent === 'pending') return;
      if (intent === 'scroll') {
        clearPendingBody();
        return;
      }
      const startY = pending.startY;
      clearPendingBody();
      beginDrag(moveEvent, {
        startY,
        captureTarget: sheetRef.current,
      });
      const session = dragRef.current;
      if (session) {
        const deltaY = moveEvent.clientY - session.startY;
        if (Math.abs(deltaY) > 6) session.moved = true;
        session.lastY = moveEvent.clientY;
        session.lastTime = moveEvent.timeStamp;
        setDragHeightPx(
          Math.min(
            session.maxHeight,
            Math.max(session.minHeight, session.startHeight - deltaY),
          ),
        );
      }
    };

    const onPointerUp = (upEvent: PointerEvent) => {
      const pending = pendingBodyRef.current;
      if (!pending || upEvent.pointerId !== pending.pointerId) return;
      clearPendingBody();
    };

    const onPointerCancel = (cancelEvent: PointerEvent) => {
      const pending = pendingBodyRef.current;
      if (!pending || cancelEvent.pointerId !== pending.pointerId) return;
      clearPendingBody();
    };

    pendingListenersRef.current = {
      move: onPointerMove,
      up: onPointerUp,
      cancel: onPointerCancel,
    };
    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
    window.addEventListener('pointercancel', onPointerCancel);
  };

  const dragging = dragHeightPx !== null;

  return (
    <section
      ref={sheetRef}
      className={`map-first__results-sheet map-first__sheet map-first__sheet--${sheetSnap}${
        hasResults ? '' : ' map-first__sheet--empty'
      }${dragging ? ' map-first__sheet--dragging' : ''}`}
      aria-label="경로 결과"
      data-sheet-snap={sheetSnap}
      style={
        dragging
          ? { height: `${dragHeightPx}px`, maxHeight: `${dragHeightPx}px` }
          : undefined
      }
    >
      <div className="map-first__sheet-stack">
        <InstallPrompt />
        <button
          type="button"
          className="map-first__sheet-toggle"
          aria-expanded={sheetSnapAriaExpanded(sheetSnap)}
          aria-controls={showBody ? bodyId : undefined}
          aria-label={sheetSnapToggleLabel(sheetSnap)}
          onClick={onToggleClick}
          onPointerDown={onTogglePointerDown}
        >
          <span className="map-first__sheet-handle" aria-hidden="true">
            <span className="map-first__sheet-handle-bar" />
          </span>
          <span className="map-first__sheet-header">
            <span className="map-first__sheet-title">{sheetTitle}</span>
            <span className="map-first__sheet-meta">{sheetMeta}</span>
          </span>
        </button>

        {showBody && (
          <div
            id={bodyId}
            ref={bodyRef}
            className="map-first__sheet-body"
            onPointerDown={onBodyPointerDown}
          >
            {loading && (
              <p className="map-first__empty-state" role="status">
                경로를 찾고 있어요…
              </p>
            )}
            {!loading && ranked.length > 0 && (
              <>
                <button
                  type="button"
                  className="map-first__departure-btn"
                  aria-haspopup="dialog"
                  aria-expanded={departureDrawerOpen}
                  disabled={loading}
                  onClick={onOpenDeparture}
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
                  onSelectRoute={onSelectRoute}
                  onDetails={onDetails}
                />
              </>
            )}
            {!loading && ranked.length === 0 && <CollapsedGuide />}
          </div>
        )}
      </div>
    </section>
  );
}
