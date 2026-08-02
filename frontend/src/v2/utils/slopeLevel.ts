/**
 * 경사도 등급 판정·대표색 공통 유틸.
 * 경계는 닫힌 상한을 포함한다: ≤2 완만, ≤5 보통, ≤8 급경사, >8 매우 급경사.
 */

export type SlopeLevelId = 'gentle' | 'moderate' | 'steep' | 'very-steep';

/** 지도 경로·범례 표식용 대표색 (CSS --mf-slope-* 와 동일) */
export const SLOPE_MAP_COLORS: Record<SlopeLevelId, string> = {
  gentle: '#2FAE6B',
  moderate: '#F7C948',
  steep: '#F58A2A',
  'very-steep': '#E3362D',
};

export const SLOPE_LEVEL_LABELS: Record<SlopeLevelId, string> = {
  gentle: '완만',
  moderate: '보통',
  steep: '급경사',
  'very-steep': '매우 급경사',
};

export type SlopeLegendBand = {
  id: SlopeLevelId;
  /** 닫힌 상한. 마지막 등급은 Infinity. */
  max: number;
  color: string;
  label: string;
  legendText: string;
};

export const SLOPE_LEGEND_BANDS: SlopeLegendBand[] = [
  {
    id: 'gentle',
    max: 2,
    color: SLOPE_MAP_COLORS.gentle,
    label: SLOPE_LEVEL_LABELS.gentle,
    legendText: '완만 ≤2%',
  },
  {
    id: 'moderate',
    max: 5,
    color: SLOPE_MAP_COLORS.moderate,
    label: SLOPE_LEVEL_LABELS.moderate,
    legendText: '보통 ≤5%',
  },
  {
    id: 'steep',
    max: 8,
    color: SLOPE_MAP_COLORS.steep,
    label: SLOPE_LEVEL_LABELS.steep,
    legendText: '급경사 ≤8%',
  },
  {
    id: 'very-steep',
    max: Infinity,
    color: SLOPE_MAP_COLORS['very-steep'],
    label: SLOPE_LEVEL_LABELS['very-steep'],
    legendText: '매우 급경사 >8%',
  },
];

/** KakaoMap / 범례 호환용 { max, color, label } 램프 */
export const SLOPE_COLOR_RAMP: Array<{
  max: number;
  color: string;
  label: string;
}> = SLOPE_LEGEND_BANDS.map(({ max, color, label }) => ({ max, color, label }));

/**
 * 경사(%) → 등급. null/undefined/NaN/비유한값은 null.
 * 절대값으로 판정한다 (오르막·내리막 동일).
 */
export function resolveSlopeLevel(
  slopePercent: number | null | undefined,
): SlopeLevelId | null {
  if (typeof slopePercent !== 'number' || !Number.isFinite(slopePercent)) {
    return null;
  }
  const abs = Math.abs(slopePercent);
  if (abs <= 2) return 'gentle';
  if (abs <= 5) return 'moderate';
  if (abs <= 8) return 'steep';
  return 'very-steep';
}

/** 지도 구간 색. 등급을 못 정하면 fallback (기본 도보색 등). */
export function slopeMapColor(
  slopePercent: number | null | undefined,
  fallback: string,
): string {
  const level = resolveSlopeLevel(slopePercent);
  return level ? SLOPE_MAP_COLORS[level] : fallback;
}

export function slopeLevelLabel(
  slopePercent: number | null | undefined,
): string {
  const level = resolveSlopeLevel(slopePercent);
  return level ? SLOPE_LEVEL_LABELS[level] : '';
}

/**
 * 표시용 경사 숫자. 최대 소수 2자리, 불필요한 0 제거.
 * 예: 8 → "8", 8.01 → "8.01", 11.2 → "11.2"
 */
export function formatSlopePercent(
  slopePercent: number | null | undefined,
): string | null {
  if (typeof slopePercent !== 'number' || !Number.isFinite(slopePercent)) {
    return null;
  }
  return Math.abs(slopePercent)
    .toFixed(2)
    .replace(/\.?0+$/, '');
}

/**
 * UI "최대 경사"(양방향 절댓값 최대).
 * avg는 |grade| 가중평균, max/min은 부호 있는 오르막·내리막 극값이다.
 * min·max가 모두 있을 때만 max(|max|, |min|)를 반환하고,
 * 한쪽만 있으면 추측하지 않고 null을 반환한다.
 */
export function resolvePeakSlopePercent(
  maxSlopePercent: number | null | undefined,
  minSlopePercent: number | null | undefined,
): number | null {
  const hasMax =
    typeof maxSlopePercent === 'number' && Number.isFinite(maxSlopePercent);
  const hasMin =
    typeof minSlopePercent === 'number' && Number.isFinite(minSlopePercent);
  if (!hasMax || !hasMin) return null;
  return Math.max(Math.abs(maxSlopePercent), Math.abs(minSlopePercent));
}
