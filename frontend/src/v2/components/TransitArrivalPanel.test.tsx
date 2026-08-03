// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { adapters } from '@/adapters';
import type { ScoredRoute } from '@/types';
import TransitArrivalPanel from './TransitArrivalPanel';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function item(): ScoredRoute {
  return {
    routeSetToken: 'route-set-token-1234567890',
    route: {
      id: 'route-1',
      summary: '버스 + 지하철',
      origin: '출발',
      destination: '도착',
      segments: [{
        id: 'bus-1',
        mode: 'bus',
        description: '100 · 부산역 → 서면역',
        durationMin: 10,
        busRouteName: '100',
        smartShelterName: '부산역',
      }, {
        id: 'subway-1',
        mode: 'subway',
        description: '부산 1호선 · 서면역 → 동래역',
        durationMin: 12,
        transitDirection: '노포',
        fastBoardingPosition: '3-2',
        startExitNo: '8',
      }],
      totalDurationMin: 22,
      totalWalkM: 0,
      transferCount: 1,
    },
    score: {
      routeId: 'route-1',
      components: {},
      display: {},
      finalScore: 80,
      lowFloorStatus: 'unknown',
      reasons: [],
      cautions: [],
      voiceSummary: '경로',
    },
  };
}

describe('선택 경로 대중교통 도착 안내', () => {
  it('상세를 열 때만 도착정보를 조회하고 시간표·환승 위치를 구분한다', async () => {
    const getTransitArrivals = vi
      .spyOn(adapters.routes, 'getTransitArrivals')
      .mockResolvedValue({
        routeId: 'route-1',
        arrivals: [{
          segmentId: 'bus-1',
          mode: 'bus',
          status: 'live',
          arrivalMin: 3,
          observedAt: '2026-08-03T01:00:00Z',
          source: '부산 BIMS',
        }, {
          segmentId: 'subway-1',
          mode: 'subway',
          status: 'scheduled',
          arrivalMin: 5,
          departureTime: '10:05:00',
          observedAt: '2026-08-03T01:00:00Z',
          source: 'ODsay 지하철 시간표',
        }],
      });

    render(<TransitArrivalPanel item={item()} />);

    expect(getTransitArrivals).toHaveBeenCalledWith(
      'route-set-token-1234567890',
      'route-1',
    );
    await waitFor(() => {
      expect(screen.getByText('3분 후 도착')).toBeTruthy();
      expect(screen.getByText('5분 후 출발 예정 (10:05:00)')).toBeTruthy();
    });
    expect(screen.getByText('빠른 환승 승차 위치 3-2')).toBeTruthy();
    expect(screen.getByText(/시간표 기준이며 실시간 열차 위치/)).toBeTruthy();
    expect(screen.getByText(/스마트쉘터 정류장을 이용하는 경로/)).toBeTruthy();
  });
});
