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
});
