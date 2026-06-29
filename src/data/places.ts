import type { Place } from '@/types';

/**
 * 부산진구(서면 일대) 대표 장소 mock.
 * 좌표는 데모용 근사값. 실제 연동 시 Kakao 장소검색 결과로 대체된다.
 */
export const PLACES: Place[] = [
  { id: 'seomyeon-stn', name: '서면역', category: '지하철역', lat: 35.1578, lng: 129.0594, address: '부산진구 중앙대로 지하' },
  { id: 'bujeon-stn', name: '부전역', category: '지하철역', lat: 35.1631, lng: 129.0608, address: '부산진구 동천로' },
  { id: 'yangjeong-stn', name: '양정역', category: '지하철역', lat: 35.1733, lng: 129.0686, address: '부산진구 중앙대로' },
  { id: 'gaya-stn', name: '가야역', category: '지하철역', lat: 35.149, lng: 129.036, address: '부산진구 가야대로' },
  { id: 'gu-office', name: '부산진구청', category: '관공서', lat: 35.1626, lng: 129.053, address: '부산진구 시민공원로' },
  { id: 'citizens-park', name: '부산시민공원', category: '공원', lat: 35.169, lng: 129.056, address: '부산진구 시민공원로' },
  { id: 'lotte-seomyeon', name: '롯데백화점 부산본점', category: '쇼핑', lat: 35.1556, lng: 129.0596, address: '부산진구 가야대로' },
  { id: 'songsanghyeon', name: '송상현광장', category: '광장', lat: 35.166, lng: 129.057, address: '부산진구 중앙대로' },
  { id: 'seomyeon-mall', name: '서면지하상가', category: '쇼핑', lat: 35.1577, lng: 129.059, address: '부산진구 중앙대로 지하' },
  { id: 'jin-market', name: '부전시장', category: '시장', lat: 35.1612, lng: 129.0605, address: '부산진구 중앙대로' },
];

export function findPlace(id: string): Place | undefined {
  return PLACES.find((p) => p.id === id);
}

/** 이름 부분일치 검색(장소검색 어댑터 mock용) */
export function searchPlacesByName(query: string): Place[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  return PLACES.filter(
    (p) => p.name.toLowerCase().includes(q) || (p.address ?? '').toLowerCase().includes(q),
  );
}
