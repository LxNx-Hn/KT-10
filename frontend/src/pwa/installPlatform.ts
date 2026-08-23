export type StandaloneProbe = {
  standalone?: boolean;
  displayModeStandalone?: boolean;
};

/**
 * iPhone / iPad / iPadOS Safari 계열.
 * Mac desktop Safari는 maxTouchPoints <= 1 이므로 제외한다.
 */
export function isIosLikePlatform(
  userAgent: string,
  platform: string,
  maxTouchPoints: number,
): boolean {
  if (/iPhone|iPad|iPod/i.test(userAgent)) return true;

  const macLikePlatform =
    platform === 'MacIntel'
    || /^Mac/i.test(platform);

  return macLikePlatform && maxTouchPoints > 1;
}

export function isAndroidPlatform(userAgent: string): boolean {
  return /Android/i.test(userAgent);
}

export function isPwaStandalone(probe?: StandaloneProbe): boolean {
  if (probe) {
    if (probe.standalone === true) return true;
    if (probe.displayModeStandalone === true) return true;
    return false;
  }

  if (typeof window === 'undefined') return false;

  const nav = navigator as Navigator & { standalone?: boolean };
  if (nav.standalone === true) return true;
  if (typeof window.matchMedia !== 'function') return false;
  return window.matchMedia('(display-mode: standalone)').matches;
}
