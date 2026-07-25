import { describe, expect, it } from 'vitest';
import { resolveDataSource } from './index';

describe('프론트 데이터 소스 기본값', () => {
  it('환경값이 없어도 실제 백엔드를 기본으로 사용한다', () => {
    expect(resolveDataSource(undefined)).toBe('live');
    expect(resolveDataSource('')).toBe('live');
  });

  it('mock은 명시적으로 지정한 경우에만 사용한다', () => {
    expect(resolveDataSource('mock')).toBe('mock');
    expect(resolveDataSource('live')).toBe('live');
  });
});
