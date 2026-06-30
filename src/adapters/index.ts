import type { Adapters } from './types';
import { mockAdapters } from './mock';
import { liveAdapters } from './live';

export type { Adapters } from './types';

/**
 * 데이터 소스 팩토리.
 * VITE_DATA_SOURCE=live → Python FastAPI 백엔드(live 어댑터) 사용.
 * 그 외(기본) → mock(부산진구 내장 데이터) 사용.
 */
export function getAdapters(): Adapters {
  const source = import.meta.env.VITE_DATA_SOURCE ?? 'mock';
  if (source === 'live') {
    console.info('[adapters] live 모드 — Python 백엔드(VITE_API_BASE)에 연결합니다.');
    return liveAdapters;
  }
  return mockAdapters;
}

export const adapters = getAdapters();
