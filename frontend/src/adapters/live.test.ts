import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { hasKakaoKey } from '@/map/kakaoLoader';
import { searchKakaoPlaces } from '@/map/kakaoPlaces';
import { liveAdapters } from './live';

vi.mock('@/map/kakaoLoader', () => ({
  hasKakaoKey: vi.fn(),
}));

vi.mock('@/map/kakaoPlaces', () => ({
  searchKakaoPlaces: vi.fn(),
}));

const BUSAN_STATION = {
  id: 'busan-station',
  name: '부산역',
  lat: 35.1151,
  lng: 129.0414,
};

beforeEach(() => {
  vi.mocked(hasKakaoKey).mockReset();
  vi.mocked(searchKakaoPlaces).mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('live 장소 검색 공급자', () => {
  it('JavaScript 키가 있으면 Kakao Places SDK를 사용한다', async () => {
    vi.mocked(hasKakaoKey).mockReturnValue(true);
    vi.mocked(searchKakaoPlaces).mockResolvedValue([BUSAN_STATION]);
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    await expect(liveAdapters.places.searchPlaces('부산역')).resolves.toEqual([
      BUSAN_STATION,
    ]);
    expect(searchKakaoPlaces).toHaveBeenCalledWith('부산역');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('백엔드 REST가 demo 출처이면 live 검색으로 표시하지 않는다', async () => {
    vi.mocked(hasKakaoKey).mockReturnValue(false);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify([BUSAN_STATION]),
      {
        status: 200,
        headers: {
          'Content-Type': 'application/json',
          'X-Place-Search-Source': 'demo',
        },
      },
    )));

    await expect(liveAdapters.places.searchPlaces('부산역')).rejects.toThrow(
      'KAKAO_PLACE_SEARCH_DEMO_SOURCE',
    );
  });

  it('백엔드가 Kakao REST 출처를 증명할 때만 결과를 사용한다', async () => {
    vi.mocked(hasKakaoKey).mockReturnValue(false);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify([BUSAN_STATION]),
      {
        status: 200,
        headers: {
          'Content-Type': 'application/json',
          'X-Place-Search-Source': 'kakao-rest',
        },
      },
    )));

    await expect(liveAdapters.places.searchPlaces('부산역')).resolves.toEqual([
      BUSAN_STATION,
    ]);
  });
});
