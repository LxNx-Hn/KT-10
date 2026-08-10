// @vitest-environment jsdom
import { cleanup, renderHook, act } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  readVisualViewportRect,
  useVisualViewportRect,
} from './useVisualViewportRect';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  Reflect.deleteProperty(window, 'visualViewport');
});

function stubVisualViewport( partial: Partial<VisualViewport> & {
  width: number;
  height: number;
  offsetTop?: number;
  offsetLeft?: number;
}) {
  const listeners = new Map<string, Set<EventListener>>();
  const vv = {
    width: partial.width,
    height: partial.height,
    offsetTop: partial.offsetTop ?? 0,
    offsetLeft: partial.offsetLeft ?? 0,
    scale: 1,
    pageLeft: 0,
    pageTop: 0,
    onresize: null,
    onscroll: null,
    addEventListener(type: string, listener: EventListener) {
      const set = listeners.get(type) ?? new Set();
      set.add(listener);
      listeners.set(type, set);
    },
    removeEventListener(type: string, listener: EventListener) {
      listeners.get(type)?.delete(listener);
    },
    dispatchEvent() {
      return false;
    },
    emit(type: string) {
      for (const listener of listeners.get(type) ?? []) {
        listener(new Event(type));
      }
    },
  };
  Object.defineProperty(window, 'visualViewport', {
    configurable: true,
    value: vv,
  });
  return vv;
}

describe('readVisualViewportRect', () => {
  it('visualViewport가 있으면 width·height·offset과 bottomInset을 계산한다', () => {
    Object.defineProperty(window, 'innerHeight', {
      configurable: true,
      value: 844,
    });
    stubVisualViewport({
      width: 390,
      height: 500,
      offsetTop: 80,
      offsetLeft: 0,
    });

    expect(readVisualViewportRect()).toEqual({
      width: 390,
      height: 500,
      offsetTop: 80,
      offsetLeft: 0,
      bottomInset: 264,
    });
  });

  it('visualViewport가 없으면 innerWidth/innerHeight로 fallback한다', () => {
    Reflect.deleteProperty(window, 'visualViewport');
    Object.defineProperty(window, 'innerWidth', {
      configurable: true,
      value: 375,
    });
    Object.defineProperty(window, 'innerHeight', {
      configurable: true,
      value: 667,
    });

    expect(readVisualViewportRect()).toEqual({
      width: 375,
      height: 667,
      offsetTop: 0,
      offsetLeft: 0,
      bottomInset: 0,
    });
  });
});

describe('useVisualViewportRect', () => {
  it('enabled일 때 resize·scroll listener를 등록하고 unmount 시 제거한다', () => {
    Object.defineProperty(window, 'innerHeight', {
      configurable: true,
      value: 844,
    });
    const vv = stubVisualViewport({
      width: 390,
      height: 700,
      offsetTop: 0,
      offsetLeft: 0,
    });
    const addSpy = vi.spyOn(vv, 'addEventListener');
    const removeSpy = vi.spyOn(vv, 'removeEventListener');
    const winAdd = vi.spyOn(window, 'addEventListener');
    const winRemove = vi.spyOn(window, 'removeEventListener');

    const { result, unmount } = renderHook(() => useVisualViewportRect(true));
    expect(result.current.height).toBe(700);
    expect(addSpy).toHaveBeenCalledWith('resize', expect.any(Function));
    expect(addSpy).toHaveBeenCalledWith('scroll', expect.any(Function));
    expect(winAdd).toHaveBeenCalledWith('resize', expect.any(Function));

    act(() => {
      vv.height = 480;
      vv.offsetTop = 120;
      vv.emit('resize');
    });
    expect(result.current).toEqual({
      width: 390,
      height: 480,
      offsetTop: 120,
      offsetLeft: 0,
      bottomInset: 244,
    });

    unmount();
    expect(removeSpy).toHaveBeenCalledWith('resize', expect.any(Function));
    expect(removeSpy).toHaveBeenCalledWith('scroll', expect.any(Function));
    expect(winRemove).toHaveBeenCalledWith('resize', expect.any(Function));
  });

  it('disabled이면 listener를 달지 않는다', () => {
    const vv = stubVisualViewport({ width: 390, height: 700 });
    const addSpy = vi.spyOn(vv, 'addEventListener');
    renderHook(() => useVisualViewportRect(false));
    expect(addSpy).not.toHaveBeenCalled();
  });

  it('visualViewport 미지원 시 window resize만 구독한다', () => {
    Reflect.deleteProperty(window, 'visualViewport');
    Object.defineProperty(window, 'innerWidth', {
      configurable: true,
      value: 320,
    });
    Object.defineProperty(window, 'innerHeight', {
      configurable: true,
      value: 568,
    });
    const winAdd = vi.spyOn(window, 'addEventListener');
    const winRemove = vi.spyOn(window, 'removeEventListener');

    const { result, unmount } = renderHook(() => useVisualViewportRect(true));
    expect(result.current.height).toBe(568);
    expect(winAdd).toHaveBeenCalledWith('resize', expect.any(Function));

    act(() => {
      Object.defineProperty(window, 'innerHeight', {
        configurable: true,
        value: 400,
      });
      window.dispatchEvent(new Event('resize'));
    });
    expect(result.current.height).toBe(400);

    unmount();
    expect(winRemove).toHaveBeenCalledWith('resize', expect.any(Function));
  });
});
