// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => {
  document.querySelectorAll('script[src*="dapi.kakao.com"]').forEach((script) => script.remove());
  delete (window as any).kakao;
  vi.unstubAllEnvs();
  vi.useRealTimers();
  vi.resetModules();
});

describe('Kakao Maps SDK loader', () => {
  it('SDK 로드 실패를 확정하고 다음 요청에서 다시 시도할 수 있다', async () => {
    vi.stubEnv('VITE_KAKAO_MAP_KEY', 'test-js-key');
    const { loadKakaoMaps } = await import('./kakaoLoader');

    const failed = loadKakaoMaps();
    const script = document.querySelector<HTMLScriptElement>('script[src*="dapi.kakao.com"]')!;
    script.dispatchEvent(new Event('error'));
    await expect(failed).rejects.toThrow('KAKAO_SDK_LOAD_FAILED');
    expect(script.isConnected).toBe(false);

    const kakao = { maps: { load: (done: () => void) => done() } };
    (window as any).kakao = kakao;
    await expect(loadKakaoMaps()).resolves.toBe(kakao);
  });

  it('SDK가 응답하지 않으면 7초 뒤 무한 대기 대신 타임아웃으로 종료한다', async () => {
    vi.useFakeTimers();
    vi.stubEnv('VITE_KAKAO_MAP_KEY', 'test-js-key');
    const { loadKakaoMaps } = await import('./kakaoLoader');

    const pending = loadKakaoMaps();
    const rejected = expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    await vi.advanceTimersByTimeAsync(7000);

    await rejected;
    expect(document.querySelector('script[src*="dapi.kakao.com"]')).toBeNull();
  });
});
