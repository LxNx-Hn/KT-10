/** 운영 빌드는 같은 출처의 /api를 사용하고, 로컬 개발만 VITE_API_BASE로 분리한다. */
export const API_BASE = (import.meta.env.VITE_API_BASE ?? '').trim().replace(/\/$/, '');

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function extractDetail(payload: unknown): string | undefined {
  if (!payload || typeof payload !== 'object') return undefined;
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return '입력값을 확인해 주세요.';
  return undefined;
}

export async function throwApiError(response: Response, action: string): Promise<never> {
  let detail: string | undefined;
  try {
    detail = extractDetail(await response.clone().json());
  } catch {
    // JSON이 아닌 오류 응답은 상태 코드만 사용한다.
  }
  throw new ApiError(`${action} (${response.status})`, response.status, detail);
}

/** 서버 내부 정보는 노출하지 않고 사용자가 다음 행동을 결정할 수 있는 문장만 보여준다. */
export function toUserMessage(error: unknown, fallback: string): string {
  if (error instanceof DOMException && error.name === 'AbortError') {
    return '서버 응답이 늦어 요청을 중단했습니다. 잠시 후 다시 시도해 주세요.';
  }
  if (
    error instanceof Error
    && [
      'NO_KAKAO_KEY',
      'KAKAO_SDK_LOAD_FAILED',
      'KAKAO_SDK_TIMEOUT',
      'KAKAO_SDK_NETWORK_ERROR',
      'KAKAO_SDK_INIT_ERROR',
      'KAKAO_PLACES_LIBRARY_UNAVAILABLE',
    ].includes(error.message)
  ) {
    return '카카오 장소 검색을 불러오지 못했습니다. JavaScript 키와 현재 도메인 등록을 확인해 주세요.';
  }
  if (error instanceof Error && error.message.startsWith('KAKAO_PLACE_SEARCH_')) {
    if (error.message === 'KAKAO_PLACE_SEARCH_DEMO_SOURCE') {
      return '카카오 장소 검색 키가 설정되지 않았습니다. 서비스 관리자에게 알려 주세요.';
    }
    return '카카오 장소 검색 요청에 실패했습니다. 잠시 후 다시 시도해 주세요.';
  }
  if (error instanceof ApiError) {
    if (error.status === 401) return '카카오 로그인 후 이용할 수 있습니다.';
    if (error.status === 404) return '요청한 정보를 찾지 못했습니다.';
    if (error.status === 422) return error.detail ?? '입력값을 다시 확인해 주세요.';
    if (error.status === 429) return '요청이 많습니다. 잠시 후 다시 시도해 주세요.';
    if (error.status === 502 || error.status === 503) {
      return '외부 데이터 제공기관에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.';
    }
  }
  if (error instanceof TypeError) {
    return '네트워크 연결을 확인한 뒤 다시 시도해 주세요.';
  }
  return fallback;
}
