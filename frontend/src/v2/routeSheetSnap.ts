/** 제스처 판정용. snap 높이는 CSS `--mf-sheet-snap-*` / 측정값이 기준. */

export type RouteSheetSnap = 'collapsed' | 'medium' | 'expanded';

export const ROUTE_SHEET_SNAPS: readonly RouteSheetSnap[] = [
  'collapsed',
  'medium',
  'expanded',
] as const;

export const ROUTE_SHEET_DRAG = {
  distanceThreshold: 48,
  /** fling도 손떨림과 구분하기 위한 최소 이동(px) */
  flingMinDistance: 24,
  velocityThreshold: 0.45,
} as const;

export function sheetSnapIndex(snap: RouteSheetSnap): number {
  return ROUTE_SHEET_SNAPS.indexOf(snap);
}

/** CSS 변수 값(`120px`, `55%`)을 px로 해석. 높이는 CSS를 단일 기준으로 둔다. */
export function resolveCssLengthPx(
  raw: string,
  percentBasePx: number,
): number | null {
  const value = raw.trim();
  if (!value) return null;
  if (value.endsWith('%')) {
    const n = Number.parseFloat(value);
    return Number.isFinite(n) ? (n / 100) * percentBasePx : null;
  }
  if (value.endsWith('px')) {
    const n = Number.parseFloat(value);
    return Number.isFinite(n) ? n : null;
  }
  const n = Number.parseFloat(value);
  return Number.isFinite(n) ? n : null;
}

/**
 * 결과 있음: collapsed → medium → expanded → collapsed
 * 빈 화면: collapsed ↔ expanded (medium 없음)
 */
export function cycleSheetSnap(
  current: RouteSheetSnap,
  hasResults = true,
): RouteSheetSnap {
  if (!hasResults) {
    return current === 'collapsed' ? 'expanded' : 'collapsed';
  }
  if (current === 'collapsed') return 'medium';
  if (current === 'medium') return 'expanded';
  return 'collapsed';
}

export function stepSheetSnap(
  current: RouteSheetSnap,
  direction: 'up' | 'down',
): RouteSheetSnap {
  const idx = sheetSnapIndex(current);
  if (direction === 'up') {
    return ROUTE_SHEET_SNAPS[Math.min(ROUTE_SHEET_SNAPS.length - 1, idx + 1)];
  }
  return ROUTE_SHEET_SNAPS[Math.max(0, idx - 1)];
}

function dragDirection(input: {
  deltaY: number;
  velocityY: number;
  farEnough: boolean;
  fastEnough: boolean;
}): 'up' | 'down' {
  const { deltaY, velocityY, farEnough, fastEnough } = input;
  if (fastEnough && (!farEnough || Math.abs(velocityY) * 100 >= Math.abs(deltaY))) {
    return velocityY > 0 ? 'down' : 'up';
  }
  return deltaY > 0 ? 'down' : 'up';
}

/**
 * deltaY > 0: 손가락이 아래로 → 시트 축소(하위 snap)
 * velocityY: px/ms, 양수면 아래 방향
 * hasResults=false이면 medium을 건너뛰고 collapsed ↔ expanded만 이동
 */
export function resolveSheetSnapFromDrag(input: {
  current: RouteSheetSnap;
  deltaY: number;
  velocityY: number;
  hasResults?: boolean;
  distanceThreshold?: number;
  flingMinDistance?: number;
  velocityThreshold?: number;
}): RouteSheetSnap {
  const distanceThreshold =
    input.distanceThreshold ?? ROUTE_SHEET_DRAG.distanceThreshold;
  const flingMinDistance =
    input.flingMinDistance ?? ROUTE_SHEET_DRAG.flingMinDistance;
  const velocityThreshold =
    input.velocityThreshold ?? ROUTE_SHEET_DRAG.velocityThreshold;
  const hasResults = input.hasResults !== false;
  const { current, deltaY, velocityY } = input;
  const absDist = Math.abs(deltaY);
  const absVel = Math.abs(velocityY);
  const farEnough = absDist >= distanceThreshold;
  const fastEnough =
    absVel >= velocityThreshold && absDist >= flingMinDistance;

  if (!farEnough && !fastEnough) return current;

  const direction = dragDirection({
    deltaY,
    velocityY,
    farEnough,
    fastEnough,
  });

  if (!hasResults) {
    if (direction === 'down') return 'collapsed';
    return 'expanded';
  }

  return stepSheetSnap(current, direction);
}

/**
 * 결과 없을 때는 peek/half/full 3단계가 아니라 collapsed ↔ empty-guide(expanded@210px).
 * medium은 결과 목록 탐색용이라 빈 화면에서는 expanded(가이드)로 보정한다.
 * (빈 expanded는 90%가 아니라 CSS empty 규칙 210px — 이름과 높이 %가 일치하지 않는 예외)
 */
export function clampSheetSnapForResults(
  snap: RouteSheetSnap,
  hasResults: boolean,
): RouteSheetSnap {
  if (!hasResults && snap === 'medium') return 'expanded';
  return snap;
}

/**
 * 본문(.route-stack) 제스처: scrollTop>0이면 항상 스크롤.
 * 최상단에서는 아래로 당길 때만 시트 축소 drag, 위로 밀면 목록 스크롤.
 */
export function resolveBodyPointerIntent(input: {
  scrollTop: number;
  deltaY: number;
  directionLockPx?: number;
}): 'pending' | 'sheet-drag' | 'scroll' {
  if (input.scrollTop > 0) return 'scroll';
  const lock = input.directionLockPx ?? 6;
  if (Math.abs(input.deltaY) < lock) return 'pending';
  // deltaY > 0: 손가락 아래 → 시트 축소 제스처
  if (input.deltaY > 0) return 'sheet-drag';
  return 'scroll';
}

export function sheetSnapShowsBody(snap: RouteSheetSnap): boolean {
  return snap !== 'collapsed';
}

export function sheetSnapAriaExpanded(snap: RouteSheetSnap): boolean {
  return snap !== 'collapsed';
}

export function sheetSnapToggleLabel(snap: RouteSheetSnap): string {
  if (snap === 'collapsed') return '경로 결과 펼치기';
  if (snap === 'medium') return '경로 결과 더 크게';
  return '경로 결과 접기';
}
