/** 사용자가 동작 감소를 요청한 경우 스크롤 애니메이션도 즉시 이동으로 바꾼다. */
export function preferredScrollBehavior(): ScrollBehavior {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return 'auto';
  }
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
}
