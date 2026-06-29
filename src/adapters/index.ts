import type { Adapters } from './types';
import { mockAdapters } from './mock';

export type { Adapters } from './types';

/**
 * 데이터 소스 팩토리.
 * VITE_DATA_SOURCE=live 이고 실 API 구현이 준비되면 live 어댑터로 교체한다.
 * 현재는 항상 mock(부산진구 데이터)을 사용한다.
 */
export function getAdapters(): Adapters {
  const source = import.meta.env.VITE_DATA_SOURCE ?? 'mock';
  if (source === 'live') {
    // TODO(live): Kakao/공공데이터(버스 도착)/기상청 어댑터 구현 후 연결
    console.warn('[adapters] live 모드 미구현 — mock 으로 폴백합니다.');
  }
  return mockAdapters;
}

export const adapters = getAdapters();
