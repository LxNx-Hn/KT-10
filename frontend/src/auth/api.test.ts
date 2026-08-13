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

describe('가입 대기 상태 조회', () => {
  it('200 pending은 pending, 204는 absent, 5xx·네트워크는 unavailable로 구분한다', async () => {
    vi.stubEnv('VITE_DATA_SOURCE', 'live');
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ pending: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(null, { status: 503 }))
      .mockRejectedValueOnce(new TypeError('network'));
    vi.stubGlobal('fetch', fetchMock);
    const { resolveSignupStatus } = await import('./api');

    await expect(resolveSignupStatus()).resolves.toEqual({ status: 'pending' });
    await expect(resolveSignupStatus()).resolves.toEqual({ status: 'absent' });
    await expect(resolveSignupStatus()).resolves.toEqual({ status: 'unavailable' });
    await expect(resolveSignupStatus()).resolves.toEqual({ status: 'unavailable' });
  });
});

describe('회원 탈퇴', () => {
  it('204면 정상 resolve한다', async () => {
    vi.stubEnv('VITE_DATA_SOURCE', 'live');
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(null, { status: 204 })),
    );
    const { withdraw } = await import('./api');

    await expect(withdraw()).resolves.toBeUndefined();
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/auth/withdraw'),
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
      }),
    );
  });

  it('401·409는 ApiError status로 구분한다', async () => {
    vi.stubEnv('VITE_DATA_SOURCE', 'live');
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(new Response(null, { status: 409 }));
    vi.stubGlobal('fetch', fetchMock);
    const { withdraw } = await import('./api');

    await expect(withdraw()).rejects.toMatchObject({ status: 401 });
    await expect(withdraw()).rejects.toMatchObject({ status: 409 });
  });

  it('기타 HTTP 오류와 네트워크 오류를 구분한다', async () => {
    vi.stubEnv('VITE_DATA_SOURCE', 'live');
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 500 }))
      .mockRejectedValueOnce(new TypeError('network'));
    vi.stubGlobal('fetch', fetchMock);
    const { withdraw } = await import('./api');

    await expect(withdraw()).rejects.toMatchObject({ status: 500 });
    await expect(withdraw()).rejects.toBeInstanceOf(TypeError);
  });
});

describe('외부 계정 삭제', () => {
  it('status는 200 verified, 204 absent, 5xx·네트워크를 구분한다', async () => {
    vi.stubEnv('VITE_DATA_SOURCE', 'live');
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ verified: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(null, { status: 503 }))
      .mockRejectedValueOnce(new TypeError('network'));
    vi.stubGlobal('fetch', fetchMock);
    const { resolveAccountDeletionStatus } = await import('./api');

    await expect(resolveAccountDeletionStatus()).resolves.toEqual({ status: 'verified' });
    await expect(resolveAccountDeletionStatus()).resolves.toEqual({ status: 'absent' });
    await expect(resolveAccountDeletionStatus()).resolves.toEqual({ status: 'unavailable' });
    await expect(resolveAccountDeletionStatus()).resolves.toEqual({ status: 'unavailable' });
  });

  it('confirm과 cancel은 credentials include이고 body에 신원을 보내지 않는다', async () => {
    vi.stubEnv('VITE_DATA_SOURCE', 'live');
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(null, { status: 204 })),
    );
    const { confirmExternalAccountDeletion, cancelExternalAccountDeletion } = await import('./api');

    await confirmExternalAccountDeletion();
    await cancelExternalAccountDeletion();
    expect(fetch).toHaveBeenNthCalledWith(
      1,
      expect.stringContaining('/api/auth/deletion/confirm'),
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
      }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      expect.stringContaining('/api/auth/deletion/cancel'),
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
      }),
    );
    const confirmInit = vi.mocked(fetch).mock.calls[0][1] as RequestInit;
    expect(confirmInit.body).toBeUndefined();
  });

  it('공개 삭제 페이지 인증은 mock에서 guest이다', async () => {
    vi.stubEnv('VITE_DATA_SOURCE', 'mock');
    const { resolveDeletionPageAuth } = await import('./api');
    await expect(resolveDeletionPageAuth()).resolves.toEqual({ status: 'guest' });
  });
});
