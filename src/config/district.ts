import type { LatLng } from '@/types';

/**
 * 발표/데모 한정 지역: 부산광역시 부산진구 (서면 일대)
 * 지도 초기 중심/범위와 데모 안내 문구를 정의한다.
 */
export const DISTRICT = {
  id: 'busanjin-gu',
  name: '부산광역시 부산진구',
  shortName: '부산진구',
  /** 지도 초기 중심: 서면역 부근 */
  center: { lat: 35.1577, lng: 129.0594 } as LatLng,
  defaultZoom: 5, // kakao map level
  /** 데모 범위 안내(검색 범위를 벗어난 입력 경고용) */
  bounds: {
    minLat: 35.13,
    maxLat: 35.19,
    minLng: 129.02,
    maxLng: 129.09,
  },
} as const;

/** 좌표가 데모 범위 안에 있는지 */
export function isInDistrict(p: LatLng): boolean {
  const b = DISTRICT.bounds;
  return (
    p.lat >= b.minLat &&
    p.lat <= b.maxLat &&
    p.lng >= b.minLng &&
    p.lng <= b.maxLng
  );
}
