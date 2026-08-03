/**
 * Kakao Map JavaScript SDK 로더.
 * VITE_KAKAO_MAP_KEY 가 있으면 SDK 를 동적 로드하고, 없으면 reject 하여
 * MapView 가 mock 스키매틱 패널로 폴백하도록 한다.
 *
 * 일시적 네트워크/타임아웃에는 짧은 지연 후 1회 자동 재시도한다.
 * 실패 시 loadPromise 를 비워 이후 호출이 다시 시도할 수 있게 한다.
 */
let loadPromise: Promise<any> | null = null;

const SDK_LOAD_TIMEOUT_MS = 15_000;
const SDK_RETRY_DELAY_MS = 500;
const SDK_SCRIPT_MARKER = 'dapi.kakao.com/v2/maps/sdk.js';

/** 키 누락·타임아웃·네트워크·초기화 실패를 서로 다른 코드로 구분한다. */
export type KakaoSdkErrorCode =
  | 'NO_KAKAO_KEY'
  | 'KAKAO_SDK_TIMEOUT'
  | 'KAKAO_SDK_NETWORK_ERROR'
  | 'KAKAO_SDK_INIT_ERROR';

export function getKakaoKey(): string {
  return (import.meta.env.VITE_KAKAO_MAP_KEY ?? '').trim();
}

export function hasKakaoKey(): boolean {
  return getKakaoKey().length > 0;
}

function logDevSdkError(code: KakaoSdkErrorCode): void {
  if (import.meta.env.DEV) {
    // 키 값은 절대 출력하지 않는다.
    console.warn(`[kakaoLoader] ${code}`);
  }
}

function findSdkScript(): HTMLScriptElement | null {
  return document.querySelector(`script[src*="${SDK_SCRIPT_MARKER}"]`);
}

function buildSdkScriptUrl(key: string): string {
  return `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(key)}&autoload=false&libraries=services`;
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function rejectSdk(
  code: KakaoSdkErrorCode,
  reject: (reason?: unknown) => void,
): void {
  logDevSdkError(code);
  reject(new Error(code));
}

/**
 * SDK script 태그는 문서에 하나만 둔다.
 * 실패 후 재시도를 위해 실패 시 기존 태그를 제거한다.
 */
function ensureSdkScript(key: string): HTMLScriptElement {
  const existing = findSdkScript();
  if (existing) return existing;

  const script = document.createElement('script');
  script.src = buildSdkScriptUrl(key);
  script.async = true;
  document.head.appendChild(script);
  return script;
}

function loadSdkOnce(): Promise<any> {
  return new Promise((resolve, reject) => {
    const key = getKakaoKey();
    if (!key) {
      rejectSdk('NO_KAKAO_KEY', reject);
      return;
    }

    const w = window as any;
    let settled = false;
    let script: HTMLScriptElement | null = null;

    const finish = (code: KakaoSdkErrorCode | null) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeoutId);
      if (code) {
        findSdkScript()?.remove();
        rejectSdk(code, reject);
        return;
      }
      resolve(w.kakao);
    };

    const timeoutId = window.setTimeout(() => {
      finish('KAKAO_SDK_TIMEOUT');
    }, SDK_LOAD_TIMEOUT_MS);

    const finishLoading = () => {
      if (!w.kakao?.maps?.load) {
        finish('KAKAO_SDK_INIT_ERROR');
        return;
      }
      try {
        w.kakao.maps.load(() => {
          if (settled) return;
          if (!w.kakao?.maps) {
            finish('KAKAO_SDK_INIT_ERROR');
            return;
          }
          finish(null);
        });
      } catch {
        finish('KAKAO_SDK_INIT_ERROR');
      }
    };

    if (w.kakao?.maps) {
      finishLoading();
      return;
    }

    script = ensureSdkScript(key);
    script.addEventListener('load', finishLoading, { once: true });
    script.addEventListener(
      'error',
      () => finish('KAKAO_SDK_NETWORK_ERROR'),
      { once: true },
    );

    // 이미 로드가 끝난 태그를 재사용할 때 load 이벤트가 다시 안 올 수 있다.
    const readyState = (script as HTMLScriptElement & { readyState?: string })
      .readyState;
    if (readyState === 'complete' || readyState === 'loaded') {
      finishLoading();
    }
  });
}

function shouldRetry(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  return (
    error.message === 'KAKAO_SDK_TIMEOUT'
    || error.message === 'KAKAO_SDK_NETWORK_ERROR'
    || error.message === 'KAKAO_SDK_INIT_ERROR'
  );
}

export function loadKakaoMaps(): Promise<any> {
  if (loadPromise) return loadPromise;

  const attempt = (async () => {
    try {
      return await loadSdkOnce();
    } catch (firstError) {
      if (!shouldRetry(firstError)) throw firstError;
      await wait(SDK_RETRY_DELAY_MS);
      return loadSdkOnce();
    }
  })();

  // 최종 실패 뒤에만 promise 를 비워 다음 호출이 재시도할 수 있게 한다.
  loadPromise = attempt.catch((error) => {
    loadPromise = null;
    throw error;
  });
  return loadPromise;
}
