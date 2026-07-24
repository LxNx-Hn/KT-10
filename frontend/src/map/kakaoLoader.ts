/**
 * Kakao Map JavaScript SDK 로더.
 * VITE_KAKAO_MAP_KEY 가 있으면 SDK 를 동적 로드하고, 없으면 reject 하여
 * MapView 가 mock 스키매틱 패널로 폴백하도록 한다.
 */
let loadPromise: Promise<any> | null = null;
const SDK_LOAD_TIMEOUT_MS = 7000;

export function getKakaoKey(): string {
  return (import.meta.env.VITE_KAKAO_MAP_KEY ?? '').trim();
}

export function hasKakaoKey(): boolean {
  return getKakaoKey().length > 0;
}

export function loadKakaoMaps(): Promise<any> {
  if (loadPromise) return loadPromise;

  const attempt = new Promise<any>((resolve, reject) => {
    const key = getKakaoKey();
    if (!key) {
      reject(new Error('NO_KAKAO_KEY'));
      return;
    }
    const w = window as any;
    let script: HTMLScriptElement | null = null;
    let settled = false;
    const timeout = window.setTimeout(() => {
      if (settled) return;
      settled = true;
      script?.remove();
      reject(new DOMException('Kakao Maps SDK timeout', 'AbortError'));
    }, SDK_LOAD_TIMEOUT_MS);
    const fail = () => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      script?.remove();
      reject(new Error('KAKAO_SDK_LOAD_FAILED'));
    };
    const finishLoading = () => {
      if (!w.kakao?.maps?.load) {
        fail();
        return;
      }
      try {
        w.kakao.maps.load(() => {
          if (settled) return;
          if (!w.kakao?.maps) {
            fail();
            return;
          }
          settled = true;
          window.clearTimeout(timeout);
          resolve(w.kakao);
        });
      } catch {
        fail();
      }
    };

    if (w.kakao?.maps) {
      finishLoading();
      return;
    }
    script = document.createElement('script');
    script.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(key)}&autoload=false&libraries=services`;
    script.async = true;
    script.onload = finishLoading;
    script.onerror = fail;
    document.head.appendChild(script);
  });

  // 일시적인 네트워크/도메인 오류 뒤에는 다음 검색에서 다시 시도할 수 있어야 한다.
  loadPromise = attempt.catch((error) => {
    loadPromise = null;
    throw error;
  });
  return loadPromise;
}
