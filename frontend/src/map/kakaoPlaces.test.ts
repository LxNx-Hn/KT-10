// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { loadKakaoMaps } from './kakaoLoader';
import { mapKakaoPlaceDocuments, searchKakaoPlaces } from './kakaoPlaces';

vi.mock('./kakaoLoader', () => ({
  loadKakaoMaps: vi.fn(),
}));

function kakaoSdk(
  callback: (
    query: string,
    done: (documents: unknown[], status: string) => void,
    options: Record<string, unknown>,
  ) => void,
) {
  class LatLng {
    constructor(
      readonly lat: number,
      readonly lng: number,
    ) {}
  }
  class LatLngBounds {
    constructor(
      readonly southWest: LatLng,
      readonly northEast: LatLng,
    ) {}
  }
  class Places {
    keywordSearch = vi.fn(callback);
  }
  return {
    maps: {
      LatLng,
      LatLngBounds,
      services: {
        Places,
        Status: { OK: 'OK', ZERO_RESULT: 'ZERO_RESULT', ERROR: 'ERROR' },
        SortBy: { ACCURACY: 'ACCURACY' },
      },
    },
  };
}

beforeEach(() => {
  vi.mocked(loadKakaoMaps).mockReset();
});

describe('Kakao JavaScript Places 검색', () => {
  it('Kakao 문서를 Place로 변환하고 부산 권역 밖·불완전 응답은 제외한다', () => {
    expect(mapKakaoPlaceDocuments([
      {
        id: 'busan-station',
        place_name: '부산역',
        x: '129.0414',
        y: '35.1151',
        category_group_name: '지하철역',
        road_address_name: '부산 동구 중앙대로 206',
      },
      { id: 'seoul', place_name: '서울역', x: '126.9707', y: '37.5547' },
      { id: 'broken', place_name: '좌표 없음' },
    ])).toEqual([
      {
        id: 'busan-station',
        name: '부산역',
        lat: 35.1151,
        lng: 129.0414,
        category: '지하철역',
        address: '부산 동구 중앙대로 206',
      },
    ]);
  });

  it('북구청을 부산 경계 rect로 검색해 실제 좌표를 반환한다', async () => {
    vi.mocked(loadKakaoMaps).mockResolvedValue(kakaoSdk((query, done, options) => {
      expect(query).toBe('북구청');
      expect(options.sort).toBe('ACCURACY');
      expect(options.bounds).toMatchObject({
        southWest: { lat: 34.8, lng: 128.7 },
        northEast: { lat: 35.5, lng: 129.4 },
      });
      done([{
        id: 'buk-gu-office',
        place_name: '부산광역시 북구청',
        x: '128.9901',
        y: '35.1970',
        category_group_name: '공공기관',
        road_address_name: '부산 북구 낙동대로1570번길 33',
      }], 'OK');
    }));

    await expect(searchKakaoPlaces(' 북구청 ')).resolves.toEqual([
      expect.objectContaining({
        id: 'buk-gu-office',
        name: '부산광역시 북구청',
        lat: 35.197,
        lng: 128.9901,
      }),
    ]);
  });

  it('Kakao ZERO_RESULT만 빈 검색 결과로 처리하고 공급자 오류는 실패시킨다', async () => {
    vi.mocked(loadKakaoMaps).mockResolvedValueOnce(kakaoSdk((_query, done) => {
      done([], 'ZERO_RESULT');
    }));
    await expect(searchKakaoPlaces('존재하지 않는 장소')).resolves.toEqual([]);

    vi.mocked(loadKakaoMaps).mockResolvedValueOnce(kakaoSdk((_query, done) => {
      done([], 'ERROR');
    }));
    await expect(searchKakaoPlaces('부산역')).rejects.toThrow('KAKAO_PLACE_SEARCH_ERROR');
  });
});
