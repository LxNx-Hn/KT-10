import { describe, expect, it } from 'vitest';
import {
  formatSlopePercent,
  formatSlopeReasonChip,
  resolvePeakSlopePercent,
  resolveSlopeLevel,
  slopeLevelLabel,
  slopeMapColor,
  SLOPE_MAP_COLORS,
  SLOPE_REASON_CHIP_LABELS,
} from './slopeLevel';

describe('resolveSlopeLevel 경계값', () => {
  it.each([
    [0, 'gentle'],
    [2, 'gentle'],
    [2.0, 'gentle'],
    [2.01, 'moderate'],
    [5, 'moderate'],
    [5.0, 'moderate'],
    [5.01, 'steep'],
    [8, 'steep'],
    [8.0, 'steep'],
    [8.01, 'very-steep'],
    [9.2, 'very-steep'],
    [-2, 'gentle'],
    [-2.01, 'moderate'],
    [-8, 'steep'],
    [-8.01, 'very-steep'],
  ] as const)('slope %s → %s', (value, expected) => {
    expect(resolveSlopeLevel(value)).toBe(expected);
  });

  it('비정상 값은 null을 반환한다', () => {
    expect(resolveSlopeLevel(null)).toBeNull();
    expect(resolveSlopeLevel(undefined)).toBeNull();
    expect(resolveSlopeLevel(Number.NaN)).toBeNull();
    expect(resolveSlopeLevel(Number.POSITIVE_INFINITY)).toBeNull();
    expect(resolveSlopeLevel(Number.NEGATIVE_INFINITY)).toBeNull();
  });
});

describe('slopeMapColor / slopeLevelLabel', () => {
  it('등급별 대표색과 한글 라벨을 반환한다', () => {
    expect(slopeMapColor(1.8, '#000')).toBe(SLOPE_MAP_COLORS.gentle);
    expect(slopeMapColor(2.6, '#000')).toBe(SLOPE_MAP_COLORS.moderate);
    expect(slopeMapColor(6.1, '#000')).toBe(SLOPE_MAP_COLORS.steep);
    expect(slopeMapColor(9.2, '#000')).toBe(SLOPE_MAP_COLORS['very-steep']);
    expect(slopeLevelLabel(2.6)).toBe('보통');
  });

  it('비정상 값은 fallback / 빈 라벨을 쓴다', () => {
    expect(slopeMapColor(undefined, '#3182f6')).toBe('#3182f6');
    expect(slopeMapColor(null, '#3182f6')).toBe('#3182f6');
    expect(slopeMapColor(Number.NaN, '#3182f6')).toBe('#3182f6');
    expect(slopeLevelLabel(undefined)).toBe('');
    expect(slopeLevelLabel(null)).toBe('');
  });
});

describe('formatSlopePercent / resolvePeakSlopePercent', () => {
  it('불필요한 0을 제거하고 최대 2자리까지 표시한다', () => {
    expect(formatSlopePercent(8)).toBe('8');
    expect(formatSlopePercent(8.0)).toBe('8');
    expect(formatSlopePercent(8.01)).toBe('8.01');
    expect(formatSlopePercent(11.2)).toBe('11.2');
    expect(formatSlopePercent(-12)).toBe('12');
  });

  it('min·max가 모두 있을 때만 절댓값 극값을 반환한다', () => {
    expect(resolvePeakSlopePercent(4.5, -12)).toBe(12);
    expect(resolvePeakSlopePercent(29.6, -4)).toBe(29.6);
    expect(resolvePeakSlopePercent(4.5, undefined)).toBeNull();
    expect(resolvePeakSlopePercent(undefined, -12)).toBeNull();
    expect(resolvePeakSlopePercent(null, null)).toBeNull();
  });
});

describe('formatSlopeReasonChip', () => {
  it('등급명에 이미 경사가 있으면 중복하지 않는다', () => {
    expect(formatSlopeReasonChip(1.5)).toBe('완만한 경사');
    expect(formatSlopeReasonChip(3.2)).toBe('보통 경사');
    expect(formatSlopeReasonChip(6.5)).toBe('급경사');
    expect(formatSlopeReasonChip(9.5)).toBe('매우 급경사');
    expect(formatSlopeReasonChip(6.5)).not.toContain('급경사 경사');
    expect(formatSlopeReasonChip(9.5)).not.toContain('매우 급경사 경사');
  });

  it('chip lookup table은 중복 "경사 경사"를 포함하지 않는다', () => {
    for (const label of Object.values(SLOPE_REASON_CHIP_LABELS)) {
      expect(label).not.toMatch(/경사 경사/);
    }
  });
});
