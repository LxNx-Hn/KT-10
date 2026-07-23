// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { ApiError, throwApiError, toUserMessage } from './http';

describe('API 오류 사용자 메시지', () => {
  it('외부 공급자 장애를 내부 상세 대신 안전한 문장으로 표시한다', () => {
    const error = new ApiError('provider failed', 502, 'private upstream detail');
    expect(toUserMessage(error, 'fallback')).toBe(
      '외부 데이터 제공기관에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.',
    );
  });

  it('422 입력 오류는 서버의 검증 문장을 보존한다', () => {
    const error = new ApiError('invalid input', 422, '부산 서비스 범위 안의 장소를 선택해 주세요.');
    expect(toUserMessage(error, 'fallback')).toBe(
      '부산 서비스 범위 안의 장소를 선택해 주세요.',
    );
  });

  it('JSON 오류 응답의 detail을 ApiError로 변환한다', async () => {
    const response = new Response(JSON.stringify({ detail: '필수 키가 없습니다.' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    });
    await expect(throwApiError(response, '요청 실패')).rejects.toMatchObject({
      status: 503,
      detail: '필수 키가 없습니다.',
    });
  });
});
