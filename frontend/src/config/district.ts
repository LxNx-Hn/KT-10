import type { LatLng } from '@/types';

/**
 * 서비스 권역은 부산 전역이며 실제 MVP 검증은 부산역 일대를 우선한다.
 */
export const DISTRICT = {
  id: 'busan',
  name: '부산광역시 전역',
  shortName: '부산',
  /** 지도 초기 중심: 부산시청 부근 */
  center: { lat: 35.1798, lng: 129.0750 } as LatLng,
  defaultZoom: 9, // kakao map level
  mvpArea: '부산역 일대',
  bounds: {
    minLat: 34.8,
    maxLat: 35.5,
    minLng: 128.7,
    maxLng: 129.4,
  },
} as const;

/** 좌표가 부산 서비스 범위 안에 있는지 */
export function isInDistrict(p: LatLng): boolean {
  const b = DISTRICT.bounds;
  return (
    p.lat >= b.minLat &&
    p.lat <= b.maxLat &&
    p.lng >= b.minLng &&
    p.lng <= b.maxLng
  );
}
