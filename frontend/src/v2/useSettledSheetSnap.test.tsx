/** @vitest-environment jsdom */
import {
  act,
  cleanup,
  renderHook,
  waitFor,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useSettledSheetSnap } from './useSettledSheetSnap';
import type { RouteSheetSnap } from './routeSheetSnap';

function dispatchSheetTransition(
  sheet: HTMLElement,
  propertyName: string,
) {
  const event = new Event('transitionend', { bubbles: true });
  Object.defineProperty(event, 'propertyName', {
    configurable: true,
    value: propertyName,
  });
  sheet.dispatchEvent(event);
}

describe('useSettledSheetSnap', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'requestAnimationFrame',
      (callback: FrameRequestCallback) => {
        callback(0);
        return 1;
      },
    );
    vi.stubGlobal('cancelAnimationFrame', () => {});
  });

  afterEach(() => {
    cleanup();
    document.body.replaceChildren();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('keeps settled snap until height transition completes', async () => {
    const sheet = document.createElement('div');
    sheet.className = 'map-first__results-sheet map-first__sheet';
    document.body.append(sheet);
    vi.spyOn(window, 'getComputedStyle').mockReturnValue({
      transitionDuration: '0.2s',
      transitionDelay: '0s',
    } as CSSStyleDeclaration);

    const { result, rerender } = renderHook(
      ({ snap }: { snap: RouteSheetSnap }) => useSettledSheetSnap(snap),
      { initialProps: { snap: 'medium' as RouteSheetSnap } },
    );
    expect(result.current).toBe('medium');

    rerender({ snap: 'expanded' });
    expect(result.current).toBe('medium');

    act(() => {
      dispatchSheetTransition(sheet, 'height');
    });

    await waitFor(() => {
      expect(result.current).toBe('expanded');
    });
  });

  it('ignores unrelated transition property and settles only the latest snap', async () => {
    const sheet = document.createElement('div');
    sheet.className = 'map-first__results-sheet map-first__sheet';
    document.body.append(sheet);
    vi.spyOn(window, 'getComputedStyle').mockReturnValue({
      transitionDuration: '0.2s',
      transitionDelay: '0s',
    } as CSSStyleDeclaration);

    const { result, rerender } = renderHook(
      ({ snap }: { snap: RouteSheetSnap }) => useSettledSheetSnap(snap),
      { initialProps: { snap: 'collapsed' as RouteSheetSnap } },
    );

    rerender({ snap: 'medium' });
    act(() => {
      dispatchSheetTransition(sheet, 'color');
    });
    expect(result.current).toBe('collapsed');

    rerender({ snap: 'expanded' });
    act(() => {
      dispatchSheetTransition(sheet, 'max-height');
    });

    await waitFor(() => {
      expect(result.current).toBe('expanded');
    });
  });

  it('settles on the next frames when transition duration is zero', async () => {
    const sheet = document.createElement('div');
    sheet.className = 'map-first__results-sheet map-first__sheet';
    document.body.append(sheet);
    vi.spyOn(window, 'getComputedStyle').mockReturnValue({
      transitionDuration: '0s',
      transitionDelay: '0s',
    } as CSSStyleDeclaration);

    const { result, rerender } = renderHook(
      ({ snap }: { snap: RouteSheetSnap }) => useSettledSheetSnap(snap),
      { initialProps: { snap: 'medium' as RouteSheetSnap } },
    );

    rerender({ snap: 'expanded' });
    await waitFor(() => {
      expect(result.current).toBe('expanded');
    });
  });
});
