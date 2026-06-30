import type { BusStopArrivals } from '@/types';
import busJson from '@data/bus_arrivals.json';

/**
 * 정류장별 버스 도착 — 공유 데이터셋(data/bus_arrivals.json).
 * 저상버스 여부는 true/false/미확인(필드 생략=undefined) 3값으로 구성한다.
 */
export const BUS_ARRIVALS = busJson as unknown as Record<string, BusStopArrivals>;

export const BUS_STOP_LIST = Object.values(BUS_ARRIVALS);

export function getArrivals(stopId: string): BusStopArrivals | undefined {
  return BUS_ARRIVALS[stopId];
}
