import { describe, expect, it } from 'vitest';
import { formatDurationMin } from './formatDurationMin';

describe('formatDurationMin', () => {
  it.each([
    [59, '59분'],
    [60, '1시간'],
    [69, '1시간 9분'],
    [71, '1시간 11분'],
    [120, '2시간'],
    [131, '2시간 11분'],
  ] as const)('%s분 → %s', (input, expected) => {
    expect(formatDurationMin(input)).toBe(expected);
  });

  it('Math.round 기준으로 반올림한다', () => {
    expect(formatDurationMin(59.4)).toBe('59분');
    expect(formatDurationMin(59.5)).toBe('1시간');
    expect(formatDurationMin(69.4)).toBe('1시간 9분');
  });

  it('음수·비정상 값을 방어한다', () => {
    expect(formatDurationMin(-3)).toBe('0분');
    expect(formatDurationMin(Number.NaN)).toBe('0분');
    expect(formatDurationMin(Number.POSITIVE_INFINITY)).toBe('0분');
  });
});
