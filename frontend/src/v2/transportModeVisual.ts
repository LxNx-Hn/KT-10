import type { RouteSegment, SegmentMode } from '@/types';

/**
 * 지도 polyline ↔ 경로 카드 이동수단 chip이 공유하는 색.
 * 그늘(#00b84a)·경사 ramp와 겹치지 않도록 도보는 차콜색으로 구분한다.
 */
export const TRANSPORT_MODE_COLOR = {
  walk: '#475569',
  bus: '#3182f6',
  /** 호선을 모르는 지하철 fallback (카드·지도 공통). */
  subway: '#7c3aed',
  transfer: '#64748b',
} as const;

/**
 * 예비 경로 색. 건물 그늘 stroke(#64748b)·fill(#8290a8) 및 선택 경로
 * 버스/지하철/경사 ramp와 겹치지 않는 낮은 채도의 웜 타우페.
 */
export const ALTERNATIVE_ROUTE_COLOR = '#7a6a58';

export type TransportSubwayLineId =
  | 'busan-1'
  | 'busan-2'
  | 'busan-3'
  | 'busan-4'
  | 'busan-gimhae'
  | 'donghae'
  | 'unknown';

/** 경로 카드 CSS(--mf-transit-line)와 동일한 부산 도시철도 노선색. */
export const SUBWAY_LINE_COLOR: Record<TransportSubwayLineId, string> = {
  'busan-1': '#f06a00',
  'busan-2': '#81bf48',
  'busan-3': '#bb8c00',
  'busan-4': '#217dcb',
  'busan-gimhae': '#8652a1',
  donghae: '#0054a6',
  unknown: TRANSPORT_MODE_COLOR.subway,
};

const SUBWAY_LINE_PATTERNS: Array<{
  id: Exclude<TransportSubwayLineId, 'unknown'>;
  label: string;
  pattern: RegExp;
}> = [
  {
    id: 'busan-gimhae',
    label: '부산김해경전철',
    pattern: /(?:부산\s*[-·]?\s*김해|김해)\s*경전철/i,
  },
  { id: 'donghae', label: '동해선', pattern: /동해선/i },
  {
    id: 'busan-1',
    label: '1호선',
    pattern: /(?:부산(?:도시철도)?\s*)?1\s*호선/i,
  },
  {
    id: 'busan-2',
    label: '2호선',
    pattern: /(?:부산(?:도시철도)?\s*)?2\s*호선/i,
  },
  {
    id: 'busan-3',
    label: '3호선',
    pattern: /(?:부산(?:도시철도)?\s*)?3\s*호선/i,
  },
  {
    id: 'busan-4',
    label: '4호선',
    pattern: /(?:부산(?:도시철도)?\s*)?4\s*호선/i,
  },
];

export function resolveSubwayLine(
  segment: Pick<RouteSegment, 'transitRouteId' | 'description'>,
): { id: TransportSubwayLineId; label?: string } {
  const source = [segment.transitRouteId, segment.description]
    .filter((value): value is string => Boolean(value?.trim()))
    .join(' ');
  const matched = SUBWAY_LINE_PATTERNS.find(({ pattern }) =>
    pattern.test(source),
  );
  return matched
    ? { id: matched.id, label: matched.label }
    : { id: 'unknown' };
}

export function subwayStrokeColor(
  lineId: TransportSubwayLineId | undefined,
): string {
  return SUBWAY_LINE_COLOR[lineId ?? 'unknown'];
}

export function transportModeStrokeColor(
  mode: SegmentMode | undefined,
  options?: {
    slopePercent?: number | null;
    subwayLineId?: TransportSubwayLineId;
    /** 경사값 없을 때 도보 fallback. 기본은 차콜 walk색. */
    walkFallback?: string;
    slopeColorFn?: (slopePercent: number) => string;
  },
): string {
  if (mode === 'walk') {
    if (
      typeof options?.slopePercent === 'number'
      && options.slopeColorFn
    ) {
      return options.slopeColorFn(options.slopePercent);
    }
    return options?.walkFallback ?? TRANSPORT_MODE_COLOR.walk;
  }
  if (mode === 'subway') {
    return subwayStrokeColor(options?.subwayLineId);
  }
  if (mode === 'bus') return TRANSPORT_MODE_COLOR.bus;
  if (mode === 'transfer') return TRANSPORT_MODE_COLOR.transfer;
  return TRANSPORT_MODE_COLOR.bus;
}

/**
 * 선 스타일은 제품 시각 언어다. estimated geometry를 exact로 바꾸지 않는다.
 * 버스·지하철은 품질과 무관하게 실선. 일반 도보는 차콜 점선.
 * 경사 overlay가 켠 도보 구간만 경사색 가독성을 위해 실선이다.
 */
export function transportModeStrokeStyle(
  mode: SegmentMode | undefined,
  quality: string | undefined,
  options?: { slopePercent?: number | null },
): string {
  if (mode === 'bus' || mode === 'subway') return 'solid';
  if (mode === 'walk') {
    return typeof options?.slopePercent === 'number' ? 'solid' : 'shortdash';
  }
  return quality === 'exact' ? 'solid' : 'shortdash';
}
