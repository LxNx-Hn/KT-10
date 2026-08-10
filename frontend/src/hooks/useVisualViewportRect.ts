import { useEffect, useState } from 'react';

export type VisualViewportRect = {
  width: number;
  height: number;
  offsetTop: number;
  offsetLeft: number;
  /** layout viewport 하단과 visual viewport 하단 사이 간격(px). */
  bottomInset: number;
};

function fallbackRect(): VisualViewportRect {
  if (typeof window === 'undefined') {
    return {
      width: 0,
      height: 0,
      offsetTop: 0,
      offsetLeft: 0,
      bottomInset: 0,
    };
  }
  return {
    width: window.innerWidth,
    height: window.innerHeight,
    offsetTop: 0,
    offsetLeft: 0,
    bottomInset: 0,
  };
}

/** visualViewport가 있으면 사용하고, 없으면 innerWidth/Height로 대체한다. */
export function readVisualViewportRect(): VisualViewportRect {
  if (typeof window === 'undefined') return fallbackRect();
  const vv = window.visualViewport;
  if (!vv) return fallbackRect();
  const bottomInset = Math.max(
    0,
    window.innerHeight - vv.height - vv.offsetTop,
  );
  return {
    width: vv.width,
    height: vv.height,
    offsetTop: vv.offsetTop,
    offsetLeft: vv.offsetLeft,
    bottomInset,
  };
}

/**
 * MOB-22: iOS 키보드 등으로 visual viewport가 줄어도
 * 고정 패널이 현재 보이는 영역 안에 남도록 수치를 구독한다.
 */
export function useVisualViewportRect(enabled: boolean): VisualViewportRect {
  const [rect, setRect] = useState<VisualViewportRect>(() => (
    enabled ? readVisualViewportRect() : fallbackRect()
  ));

  useEffect(() => {
    if (!enabled) return undefined;

    const update = () => {
      setRect(readVisualViewportRect());
    };

    update();

    const vv = window.visualViewport;
    if (vv) {
      vv.addEventListener('resize', update);
      vv.addEventListener('scroll', update);
      window.addEventListener('resize', update);
      return () => {
        vv.removeEventListener('resize', update);
        vv.removeEventListener('scroll', update);
        window.removeEventListener('resize', update);
      };
    }

    window.addEventListener('resize', update);
    return () => {
      window.removeEventListener('resize', update);
    };
  }, [enabled]);

  return rect;
}
