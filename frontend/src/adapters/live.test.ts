import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { hasKakaoKey } from '@/map/kakaoLoader';
import { searchKakaoPlaces } from '@/map/kakaoPlaces';
import { liveAdapters } from './live';
import type { ScoredRoute } from '@/types';

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
  vi.useRealTimers();
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

describe('live 경로 요청 제한시간', () => {
  it('첫 화면을 오래 막지 않도록 경로 요청을 20초에 중단한다', async () => {
    vi.useFakeTimers();
    let requestSignal: AbortSignal | undefined;
    vi.stubGlobal('fetch', vi.fn((_url: string, init?: RequestInit) => {
      requestSignal = init?.signal ?? undefined;
      return new Promise<Response>((_resolve, reject) => {
        requestSignal?.addEventListener('abort', () => {
          reject(new DOMException('aborted', 'AbortError'));
        });
      });
    }));

    const request = liveAdapters.routes.recommend(
      BUSAN_STATION,
      { ...BUSAN_STATION, id: 'destination', name: '북구청' },
      'general',
      'normal',
      {},
    );
    const rejection = expect(request).rejects.toMatchObject({
      name: 'AbortError',
    });

    await vi.advanceTimersByTimeAsync(7_000);
    expect(requestSignal?.aborted).toBe(false);

    await vi.advanceTimersByTimeAsync(13_000);
    expect(requestSignal?.aborted).toBe(true);
    await rejection;
  });

  it('시간 변경은 기존 후보 토큰으로 그늘 갱신 endpoint만 호출한다', async () => {
    const token = 'route-set-token-1234567890';
    const current = [{ routeSetToken: token }] as ScoredRoute[];
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify([]),
      {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      },
    ));
    vi.stubGlobal('fetch', fetchMock);

    await liveAdapters.routes.refreshShade(
      current,
      'general',
      'normal',
      { departureAt: '2026-07-24T02:00:00+09:00' },
    );

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/routes/refresh-shade');
    expect(JSON.parse(String(init.body))).toEqual({
      routeSetToken: token,
      profile: 'general',
      options: { departureAt: '2026-07-24T02:00:00+09:00' },
      topN: 3,
    });
  });
});
