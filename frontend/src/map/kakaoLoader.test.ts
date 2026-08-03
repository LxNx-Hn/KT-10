// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => {
  document.querySelectorAll('script[src*="dapi.kakao.com"]').forEach((script) => script.remove());
  delete (window as any).kakao;
  vi.unstubAllEnvs();
  vi.useRealTimers();
  vi.resetModules();
  vi.restoreAllMocks();
});

function sdkScripts(): NodeListOf<HTMLScriptElement> {
  return document.querySelectorAll('script[src*="dapi.kakao.com"]');
}

describe('Kakao Maps SDK loader', () => {
  it('네트워크 오류를 구분하고 최종 실패 후 다음 요청에서 다시 시도할 수 있다', async () => {
    vi.useFakeTimers();
    vi.stubEnv('VITE_KAKAO_MAP_KEY', 'test-js-key');
    const { loadKakaoMaps } = await import('./kakaoLoader');

    const failed = loadKakaoMaps();
    expect(sdkScripts()).toHaveLength(1);
    sdkScripts()[0]!.dispatchEvent(new Event('error'));

    await vi.advanceTimersByTimeAsync(500);
    expect(sdkScripts()).toHaveLength(1);
    sdkScripts()[0]!.dispatchEvent(new Event('error'));

    await expect(failed).rejects.toThrow('KAKAO_SDK_NETWORK_ERROR');
    expect(sdkScripts()).toHaveLength(0);

    const kakao = { maps: { load: (done: () => void) => done() } };
    (window as any).kakao = kakao;
    await expect(loadKakaoMaps()).resolves.toBe(kakao);
  });

  it('SDK가 응답하지 않으면 15초 뒤 타임아웃 코드로 종료한다', async () => {
    vi.useFakeTimers();
    vi.stubEnv('VITE_KAKAO_MAP_KEY', 'test-js-key');
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const { loadKakaoMaps } = await import('./kakaoLoader');

    const pending = loadKakaoMaps();
    const rejected = expect(pending).rejects.toThrow('KAKAO_SDK_TIMEOUT');
    // 1차 타임아웃 + 재시도 지연 + 2차 타임아웃
    await vi.advanceTimersByTimeAsync(15_000);
    await vi.advanceTimersByTimeAsync(500);
    await vi.advanceTimersByTimeAsync(15_000);

    await rejected;
    expect(sdkScripts()).toHaveLength(0);
    expect(warn).toHaveBeenCalledWith('[kakaoLoader] KAKAO_SDK_TIMEOUT');
    expect(
      warn.mock.calls.every((call) => !String(call[0]).includes('test-js-key')),
    ).toBe(true);
  });

  it('타임아웃 후 자동 재시도가 성공하면 SDK를 반환한다', async () => {
    vi.useFakeTimers();
    vi.stubEnv('VITE_KAKAO_MAP_KEY', 'test-js-key');
    const { loadKakaoMaps } = await import('./kakaoLoader');

    const pending = loadKakaoMaps();
    expect(sdkScripts()).toHaveLength(1);

    await vi.advanceTimersByTimeAsync(15_000);
    expect(sdkScripts()).toHaveLength(0);

    await vi.advanceTimersByTimeAsync(500);
    expect(sdkScripts()).toHaveLength(1);

    const kakao = { maps: { load: (done: () => void) => done() } };
    (window as any).kakao = kakao;
    sdkScripts()[0]!.dispatchEvent(new Event('load'));

    await expect(pending).resolves.toBe(kakao);
  });

  it('동시에 여러 번 호출해도 Kakao SDK script는 하나만 삽입한다', async () => {
    vi.stubEnv('VITE_KAKAO_MAP_KEY', 'test-js-key');
    const { loadKakaoMaps } = await import('./kakaoLoader');

    const first = loadKakaoMaps();
    const second = loadKakaoMaps();
    expect(sdkScripts()).toHaveLength(1);
    expect(first).toBe(second);

    const kakao = { maps: { load: (done: () => void) => done() } };
    (window as any).kakao = kakao;
    sdkScripts()[0]!.dispatchEvent(new Event('load'));
    await expect(first).resolves.toBe(kakao);
    await expect(second).resolves.toBe(kakao);
    expect(sdkScripts()).toHaveLength(1);
  });

  it('이미 script가 있으면 새로 삽입하지 않고 기존 태그를 사용한다', async () => {
    vi.stubEnv('VITE_KAKAO_MAP_KEY', 'test-js-key');
    const existing = document.createElement('script');
    existing.src =
      'https://dapi.kakao.com/v2/maps/sdk.js?appkey=test-js-key&autoload=false&libraries=services';
    existing.async = true;
    document.head.appendChild(existing);

    const { loadKakaoMaps } = await import('./kakaoLoader');
    const pending = loadKakaoMaps();
    expect(sdkScripts()).toHaveLength(1);
    expect(sdkScripts()[0]).toBe(existing);

    const kakao = { maps: { load: (done: () => void) => done() } };
    (window as any).kakao = kakao;
    existing.dispatchEvent(new Event('load'));
    await expect(pending).resolves.toBe(kakao);
  });

  it('SDK 초기화 오류는 네트워크/타임아웃과 다른 코드로 구분한다', async () => {
    vi.useFakeTimers();
    vi.stubEnv('VITE_KAKAO_MAP_KEY', 'test-js-key');
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    const { loadKakaoMaps } = await import('./kakaoLoader');

    const pending = loadKakaoMaps();
    const rejected = expect(pending).rejects.toThrow('KAKAO_SDK_INIT_ERROR');

    (window as any).kakao = { maps: {} };
    sdkScripts()[0]!.dispatchEvent(new Event('load'));

    // 재시도 지연 후, 남아 있는 불완전 kakao.maps 로 다시 INIT 오류
    await vi.advanceTimersByTimeAsync(500);
    await rejected;
  });
});
