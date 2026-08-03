import { describe, expect, it } from 'vitest';
import type { ScoredRoute } from '@/types';
import { serverRankedRecommendations } from './routes';

function route(id: string, score: number, duration: number): ScoredRoute {
  return {
    route: {
      id,
      summary: id,
      origin: '출발',
      destination: '도착',
      segments: [],
      totalDurationMin: duration,
      totalWalkM: 0,
      transferCount: 0,
    },
    score: {
      routeId: id,
      components: {},
      display: {},
      finalScore: score,
      lowFloorStatus: 'none',
      reasons: [],
      cautions: [],
      voiceSummary: id,
    },
  };
}

describe('경로 순위 계약', () => {
  it('서명된 서버 순서를 화면 점수로 다시 정렬하지 않는다', () => {
    const input = [
      route('낮은점수', 70, 20),
      route('동점느림', 80, 30),
      route('동점빠름', 80, 25),
      route('동점빠름후순위', 80, 25),
    ];

    expect(serverRankedRecommendations(input).map(({ route: item }) => item.id)).toEqual([
      '낮은점수',
      '동점느림',
      '동점빠름',
      '동점빠름후순위',
    ]);
    expect(input[0].route.id).toBe('낮은점수');
  });

  it('null/undefined 추천 배열은 빈 목록으로 취급한다', () => {
    expect(serverRankedRecommendations(null)).toEqual([]);
    expect(serverRankedRecommendations(undefined)).toEqual([]);
  });
});
