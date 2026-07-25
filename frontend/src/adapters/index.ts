import type { Adapters } from './types';
import { mockAdapters } from './mock';
import { liveAdapters } from './live';

export type { Adapters } from './types';

/**
 * 데이터 소스 팩토리.
 * mock은 테스트·명시적 데모에서만 선택한다.
 * 값이 없거나 live이면 Python FastAPI 백엔드를 사용한다.
 */
export function resolveDataSource(
  source: string | undefined,
): 'live' | 'mock' {
  return source === 'mock' ? 'mock' : 'live';
}

export function getAdapters(): Adapters {
  return resolveDataSource(import.meta.env.VITE_DATA_SOURCE) === 'mock'
    ? mockAdapters
    : liveAdapters;
}

export const adapters = getAdapters();
