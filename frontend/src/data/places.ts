import type { Place } from '@/types';
import placesJson from '@data/places.json';

/**
 * 부산진구(서면 일대) 대표 장소 — 공유 데이터셋(data/places.json).
 * 프론트엔드와 백엔드가 동일한 JSON 을 단일 소스로 사용한다.
 */
export const PLACES = placesJson as unknown as Place[];

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
