/**
 * 총 소요시간(분)을 사용자용 한국어 문구로 표시한다.
 * 60분 미만은 "N분", 이상은 "H시간" / "H시간 M분".
 * 구간(버스·도보 세그먼트)의 짧은 시간에는 쓰지 않는다.
 */
export function formatDurationMin(totalMinutes: number): string {
  if (!Number.isFinite(totalMinutes)) return '0분';
  const minutes = Math.max(0, Math.round(totalMinutes));
  if (minutes < 60) return `${minutes}분`;

  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (rest === 0) return `${hours}시간`;
  return `${hours}시간 ${rest}분`;
}
