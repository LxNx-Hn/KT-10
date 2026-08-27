import { describe, expect, it } from 'vitest';
import { formatDistanceM } from './formatDistanceM';

describe('formatDistanceM', () => {
  it('소수 첫째 자리에서 반올림하고 한 자리로 표시한다', () => {
    expect(formatDistanceM(12.34)).toBe('12.3');
    expect(formatDistanceM(12.35)).toBe('12.4');
    expect(formatDistanceM(0)).toBe('0.0');
  });
});
