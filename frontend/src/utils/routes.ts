import type { ScoredRoute } from '@/types';

/**
 * 백엔드는 순위를 확정한 뒤 그 순위를 feedbackToken에 서명한다.
 * 반올림된 화면 점수로 클라이언트가 다시 정렬하면 서명 순위와 달라질 수 있으므로
 * 지도·카드·음성·후기는 모두 응답 순서를 그대로 사용한다.
 */
export function serverRankedRecommendations(
  recommendations: ScoredRoute[],
): ScoredRoute[] {
  return [...recommendations];
}
