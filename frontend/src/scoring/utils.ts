/** 점수 범위 보정 */
export function clamp(v: number, min = 0, max = 100): number {
  return Math.min(max, Math.max(min, v));
}

/** 평균 (빈 배열이면 fallback) */
export function avg(nums: number[], fallback = 0): number {
  if (nums.length === 0) return fallback;
  return nums.reduce((a, b) => a + b, 0) / nums.length;
}

/** 소수 1자리 반올림 */
export function round1(v: number): number {
  return Math.round(v * 10) / 10;
}
