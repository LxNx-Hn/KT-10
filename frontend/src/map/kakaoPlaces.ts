import { DISTRICT, isInDistrict } from '@/config/district';
import type { Place } from '@/types';
import { loadKakaoMaps } from './kakaoLoader';

const SEARCH_TIMEOUT_MS = 7000;

type KakaoPlaceDocument = {
  id?: string;
  place_name?: string;
  x?: string;
  y?: string;
  category_group_name?: string;
  category_name?: string;
  road_address_name?: string;
  address_name?: string;
};

/** Kakao Local 응답을 앱 도메인 타입으로 바꾸고 부산 권역 밖 결과는 제외한다. */
export function mapKakaoPlaceDocuments(documents: KakaoPlaceDocument[]): Place[] {
  const places: Place[] = [];
  for (const [index, document] of documents.entries()) {
    const lat = Number(document.y);
    const lng = Number(document.x);
    const name = document.place_name?.trim();
    if (!name || !Number.isFinite(lat) || !Number.isFinite(lng)) continue;
    if (!isInDistrict({ lat, lng })) continue;
    places.push({
      id: document.id || `kakao-${lat}-${lng}-${index}`,
      name,
      lat,
      lng,
      category: document.category_group_name || document.category_name || undefined,
      address: document.road_address_name || document.address_name || undefined,
    });
  }
  return places;
}

/**
 * 지도용 JavaScript 키로 Kakao Places 키워드 검색을 수행한다.
 * 클라이언트 키가 설정된 live 빌드에서는 제한된 데모 목록 대신 이 경로를 사용한다.
 */
export async function searchKakaoPlaces(query: string): Promise<Place[]> {
  const q = query.trim();
  if (!q) return [];

  const kakao = await loadKakaoMaps();
  const services = kakao.maps?.services;
  if (!services?.Places || !services.Status) {
    throw new Error('KAKAO_PLACES_LIBRARY_UNAVAILABLE');
  }

  const bounds = new kakao.maps.LatLngBounds(
    new kakao.maps.LatLng(DISTRICT.bounds.minLat, DISTRICT.bounds.minLng),
    new kakao.maps.LatLng(DISTRICT.bounds.maxLat, DISTRICT.bounds.maxLng),
  );

  return new Promise<Place[]>((resolve, reject) => {
    const timeout = window.setTimeout(
      () => reject(new DOMException('Kakao Places timeout', 'AbortError')),
      SEARCH_TIMEOUT_MS,
    );
    const finish = (callback: () => void) => {
      window.clearTimeout(timeout);
      callback();
    };

    new services.Places().keywordSearch(
      q,
      (documents: KakaoPlaceDocument[], status: string) => {
        if (status === services.Status.OK) {
          finish(() => resolve(mapKakaoPlaceDocuments(documents)));
          return;
        }
        if (status === services.Status.ZERO_RESULT) {
          finish(() => resolve([]));
          return;
        }
        finish(() => reject(new Error(`KAKAO_PLACE_SEARCH_${status || 'FAILED'}`)));
      },
      {
        bounds,
        sort: services.SortBy?.ACCURACY,
      },
    );
  });
}
