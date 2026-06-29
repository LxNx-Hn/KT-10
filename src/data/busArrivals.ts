import type { BusStopArrivals } from '@/types';

/**
 * 정류장별 버스 도착 mock (기획서 §9).
 * 저상버스 여부는 true/false/미확인(undefined) 3값으로 구성한다.
 */
export const BUS_ARRIVALS: Record<string, BusStopArrivals> = {
  'stop-gu-office': {
    stopId: 'stop-gu-office',
    stopName: '부산진구청 정류장',
    arrivals: [
      { routeName: '81', arrivalMin: 5, isLowFloor: true, remainingStops: 3 },
      { routeName: '210', arrivalMin: 3, isLowFloor: false, remainingStops: 2 },
      { routeName: '54', arrivalMin: 9, isLowFloor: undefined, remainingStops: 6 },
    ],
  },
  'stop-seomyeon': {
    stopId: 'stop-seomyeon',
    stopName: '서면역 정류장',
    arrivals: [
      { routeName: '15', arrivalMin: 2, isLowFloor: true, remainingStops: 1 },
      { routeName: '88', arrivalMin: 7, isLowFloor: undefined, remainingStops: 4 },
      { routeName: '110', arrivalMin: 12, isLowFloor: false, remainingStops: 8 },
    ],
  },
  'stop-citizens-park': {
    stopId: 'stop-citizens-park',
    stopName: '부산시민공원 정류장',
    arrivals: [
      { routeName: '129', arrivalMin: 4, isLowFloor: true, remainingStops: 2 },
      { routeName: '63', arrivalMin: 6, isLowFloor: false, remainingStops: 5 },
    ],
  },
};

export const BUS_STOP_LIST = Object.values(BUS_ARRIVALS);

export function getArrivals(stopId: string): BusStopArrivals | undefined {
  return BUS_ARRIVALS[stopId];
}
