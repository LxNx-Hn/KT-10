import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe('로그인 상태 조회', () => {
  it('게스트 204 응답을 오류가 아닌 비로그인 상태로 처리한다', async () => {
    vi.stubEnv('VITE_DATA_SOURCE', 'live');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    const { getCurrentUser } = await import('./api');

    await expect(getCurrentUser()).resolves.toBeNull();
  });

  it('resolveCurrentAuth는 204를 guest, 503을 unavailable로 구분한다', async () => {
    vi.stubEnv('VITE_DATA_SOURCE', 'live');
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(null, { status: 503 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ id: 'u1', preference: {} }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockRejectedValueOnce(new TypeError('network'));
    vi.stubGlobal('fetch', fetchMock);
    const { resolveCurrentAuth } = await import('./api');

    await expect(resolveCurrentAuth()).resolves.toEqual({ status: 'guest' });
    await expect(resolveCurrentAuth()).resolves.toEqual({ status: 'unavailable' });
    await expect(resolveCurrentAuth()).resolves.toMatchObject({
      status: 'authenticated',
      user: { id: 'u1' },
    });
    await expect(resolveCurrentAuth()).resolves.toEqual({ status: 'unavailable' });
  });
});
