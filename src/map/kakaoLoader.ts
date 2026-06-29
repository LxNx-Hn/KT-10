/**
 * Kakao Map JavaScript SDK 로더.
 * VITE_KAKAO_MAP_KEY 가 있으면 SDK 를 동적 로드하고, 없으면 reject 하여
 * MapView 가 mock 스키매틱 패널로 폴백하도록 한다.
 */
let loadPromise: Promise<any> | null = null;

export function getKakaoKey(): string {
  return (import.meta.env.VITE_KAKAO_MAP_KEY ?? '').trim();
}

export function hasKakaoKey(): boolean {
  return getKakaoKey().length > 0;
}

export function loadKakaoMaps(): Promise<any> {
  if (loadPromise) return loadPromise;

  loadPromise = new Promise((resolve, reject) => {
    const key = getKakaoKey();
    if (!key) {
      reject(new Error('NO_KAKAO_KEY'));
      return;
    }
    const w = window as any;
    if (w.kakao?.maps) {
      resolve(w.kakao);
      return;
    }
    const script = document.createElement('script');
    script.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${key}&autoload=false&libraries=services`;
    script.async = true;
    script.onload = () => {
      w.kakao.maps.load(() => resolve(w.kakao));
    };
    script.onerror = () => reject(new Error('KAKAO_SDK_LOAD_FAILED'));
    document.head.appendChild(script);
  });

  return loadPromise;
}
