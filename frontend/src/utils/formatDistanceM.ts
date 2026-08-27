/** 보행거리를 사용자에게 소수 첫째 자리까지 반올림해 표시한다. */
export function formatDistanceM(distanceM: number): string {
  if (!Number.isFinite(distanceM)) return '0.0';
  return (Math.round(Math.max(0, distanceM) * 10) / 10).toFixed(1);
}
