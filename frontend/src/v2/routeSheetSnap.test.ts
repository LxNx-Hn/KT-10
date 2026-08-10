import { describe, expect, it } from 'vitest';
import {
  clampSheetSnapForResults,
  cycleSheetSnap,
  cssTimeTokenToMs,
  maxCssTimeListToMs,
  resolveBodyPointerIntent,
  resolveCssLengthPx,
  resolveSheetSnapFromDrag,
  sheetHeightTransitionWaitMs,
  sheetSnapLayoutFitToken,
  stepSheetSnap,
} from './routeSheetSnap';

describe('routeSheetSnap', () => {
  it('cycles toggle collapsed → medium → expanded → collapsed', () => {
    expect(cycleSheetSnap('collapsed')).toBe('medium');
    expect(cycleSheetSnap('medium')).toBe('expanded');
    expect(cycleSheetSnap('expanded')).toBe('collapsed');
  });

  it('cycles empty sheet between collapsed and expanded only', () => {
    expect(cycleSheetSnap('collapsed', false)).toBe('expanded');
    expect(cycleSheetSnap('expanded', false)).toBe('collapsed');
    expect(cycleSheetSnap('medium', false)).toBe('collapsed');
  });

  it('steps stay within bounds', () => {
    expect(stepSheetSnap('collapsed', 'down')).toBe('collapsed');
    expect(stepSheetSnap('expanded', 'up')).toBe('expanded');
    expect(stepSheetSnap('medium', 'up')).toBe('expanded');
    expect(stepSheetSnap('medium', 'down')).toBe('collapsed');
  });

  it('keeps snap under drag distance threshold', () => {
    expect(
      resolveSheetSnapFromDrag({
        current: 'medium',
        deltaY: -20,
        velocityY: 0,
      }),
    ).toBe('medium');
    expect(
      resolveSheetSnapFromDrag({
        current: 'medium',
        deltaY: 20,
        velocityY: 0,
      }),
    ).toBe('medium');
  });

  it('moves up on sufficient upward drag', () => {
    expect(
      resolveSheetSnapFromDrag({
        current: 'collapsed',
        deltaY: -60,
        velocityY: 0,
      }),
    ).toBe('medium');
    expect(
      resolveSheetSnapFromDrag({
        current: 'medium',
        deltaY: -60,
        velocityY: 0,
      }),
    ).toBe('expanded');
  });

  it('moves down on sufficient downward drag', () => {
    expect(
      resolveSheetSnapFromDrag({
        current: 'expanded',
        deltaY: 60,
        velocityY: 0,
      }),
    ).toBe('medium');
    expect(
      resolveSheetSnapFromDrag({
        current: 'medium',
        deltaY: 60,
        velocityY: 0,
      }),
    ).toBe('collapsed');
  });

  it('empty expanded down drag goes to collapsed, never medium', () => {
    expect(
      resolveSheetSnapFromDrag({
        current: 'expanded',
        deltaY: 60,
        velocityY: 0,
        hasResults: false,
      }),
    ).toBe('collapsed');
    expect(
      clampSheetSnapForResults(
        resolveSheetSnapFromDrag({
          current: 'expanded',
          deltaY: 60,
          velocityY: 0,
          hasResults: false,
        }),
        false,
      ),
    ).toBe('collapsed');
  });

  it('empty collapsed up drag goes to expanded', () => {
    expect(
      resolveSheetSnapFromDrag({
        current: 'collapsed',
        deltaY: -60,
        velocityY: 0,
        hasResults: false,
      }),
    ).toBe('expanded');
  });

  it('empty drag resolution never yields medium', () => {
    for (const current of ['collapsed', 'expanded'] as const) {
      for (const deltaY of [-80, -24, 24, 80]) {
        const next = resolveSheetSnapFromDrag({
          current,
          deltaY,
          velocityY: deltaY > 0 ? 0.6 : -0.6,
          hasResults: false,
        });
        expect(next).not.toBe('medium');
        expect(clampSheetSnapForResults(next, false)).not.toBe('medium');
      }
    }
  });

  it('respects fling velocity near threshold distance', () => {
    expect(
      resolveSheetSnapFromDrag({
        current: 'medium',
        deltaY: -24,
        velocityY: -0.6,
      }),
    ).toBe('expanded');
    expect(
      resolveSheetSnapFromDrag({
        current: 'medium',
        deltaY: 24,
        velocityY: 0.6,
      }),
    ).toBe('collapsed');
  });

  it('ignores fast velocity when travel is still a jitter', () => {
    expect(
      resolveSheetSnapFromDrag({
        current: 'medium',
        deltaY: 20,
        velocityY: 5,
      }),
    ).toBe('medium');
  });

  it('does not leave bounds at edges', () => {
    expect(
      resolveSheetSnapFromDrag({
        current: 'collapsed',
        deltaY: 80,
        velocityY: 1,
      }),
    ).toBe('collapsed');
    expect(
      resolveSheetSnapFromDrag({
        current: 'expanded',
        deltaY: -80,
        velocityY: -1,
      }),
    ).toBe('expanded');
  });

  it('clamps medium when there are no results', () => {
    expect(clampSheetSnapForResults('medium', false)).toBe('expanded');
    expect(clampSheetSnapForResults('medium', true)).toBe('medium');
    expect(clampSheetSnapForResults('collapsed', false)).toBe('collapsed');
  });

  it('resolves CSS length tokens for snap heights', () => {
    expect(resolveCssLengthPx('120px', 800)).toBe(120);
    expect(resolveCssLengthPx('55%', 800)).toBeCloseTo(440);
    expect(resolveCssLengthPx('90%', 800)).toBeCloseTo(720);
  });

  it('prefers distance direction when velocity is weak relative to travel', () => {
    expect(
      resolveSheetSnapFromDrag({
        current: 'medium',
        deltaY: -80,
        velocityY: -0.1,
      }),
    ).toBe('expanded');
    expect(
      resolveSheetSnapFromDrag({
        current: 'medium',
        deltaY: 80,
        velocityY: 0.1,
      }),
    ).toBe('collapsed');
  });

  it('starts sheet drag from body only when pulling down at scroll top', () => {
    expect(
      resolveBodyPointerIntent({ scrollTop: 0, deltaY: 12 }),
    ).toBe('sheet-drag');
    expect(
      resolveBodyPointerIntent({ scrollTop: 0, deltaY: -12 }),
    ).toBe('scroll');
    expect(
      resolveBodyPointerIntent({ scrollTop: 40, deltaY: 40 }),
    ).toBe('scroll');
    expect(
      resolveBodyPointerIntent({ scrollTop: 40, deltaY: -40 }),
    ).toBe('scroll');
    expect(
      resolveBodyPointerIntent({ scrollTop: 0, deltaY: 3 }),
    ).toBe('pending');
  });

  it('layoutFit tokens distinguish collapsed/medium/expanded', () => {
    expect(sheetSnapLayoutFitToken('collapsed')).toBe('sheet-collapsed');
    expect(sheetSnapLayoutFitToken('medium')).toBe('sheet-medium');
    expect(sheetSnapLayoutFitToken('expanded')).toBe('sheet-expanded');
    expect(sheetSnapLayoutFitToken('medium')).not.toBe(
      sheetSnapLayoutFitToken('expanded'),
    );
  });

  it('parses CSS transition times and wait budgets', () => {
    expect(cssTimeTokenToMs('0.2s')).toBe(200);
    expect(cssTimeTokenToMs('16ms')).toBe(16);
    expect(maxCssTimeListToMs('0.2s, 0.1s')).toBe(200);
    expect(sheetHeightTransitionWaitMs('0.2s', '0s', false)).toBe(200);
    expect(sheetHeightTransitionWaitMs('0.2s', '50ms', false)).toBe(250);
    expect(sheetHeightTransitionWaitMs('0.2s', '0s', true)).toBe(0);
    expect(sheetHeightTransitionWaitMs('0s', '0s', false)).toBe(0);
  });
});
