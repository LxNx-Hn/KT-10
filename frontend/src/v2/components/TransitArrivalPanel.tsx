import { useEffect, useMemo, useRef, useState } from 'react';
import { adapters } from '@/adapters';
import type { ScoredRoute, TransitArrivals } from '@/types';

/** 시간표가 주는 HH:MM:SS에서 초를 떼어 분까지만 남긴다. */
function clockSuffix(value: string | undefined): string {
  return value ? ` (${value.slice(0, 5)})` : '';
}

function arrivalLabel(
  arrival: TransitArrivals['arrivals'][number],
): string {
  // 시발역에서 타는 열차는 그 역에서 출발하고, 중간역이면 그 역에 도착한다.
  const boardsAtOrigin = arrival.boardingKind === 'origin';
  if (arrival.status === 'live') {
    if (arrival.arrivalMin === 0) return boardsAtOrigin ? '곧 출발' : '곧 도착';
    if (arrival.arrivalMin !== undefined) {
      return `${arrival.arrivalMin}분 후 ${boardsAtOrigin ? '출발' : '도착'}`;
    }
    return arrival.arrivalMessage ?? '현재 도착정보 없음';
  }
  if (arrival.status === 'scheduled') {
    const clock = clockSuffix(arrival.departureTime);
    if (arrival.arrivalMin === 0) return boardsAtOrigin ? '곧 출발' : '곧 도착';
    if (arrival.arrivalMin !== undefined) {
      return boardsAtOrigin
        ? `${arrival.arrivalMin}분 후 출발 예정${clock}`
        : `${arrival.arrivalMin}분 후 도착${clock}`;
    }
    return `시간표 출발 예정${clock}`;
  }
  return arrival.arrivalMessage ?? '도착정보 확인 불가';
}

export default function TransitArrivalPanel({ item }: { item: ScoredRoute }) {
  const transitSegments = useMemo(
    () => item.route.segments.filter(
      (segment) => segment.mode === 'bus' || segment.mode === 'subway',
    ),
    [item.route.segments],
  );
  const [result, setResult] = useState<TransitArrivals | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);

  useEffect(() => {
    const routeSetToken = item.routeSetToken;
    if (!routeSetToken || transitSegments.length === 0) {
      setResult(null);
      setLoading(false);
      setError(null);
      return;
    }
    const currentRequest = ++requestId.current;
    setLoading(true);
    setError(null);
    void adapters.routes
      .getTransitArrivals(routeSetToken, item.route.id)
      .then((next) => {
        if (currentRequest === requestId.current) setResult(next);
      })
      .catch(() => {
        if (currentRequest === requestId.current) {
          setError('대중교통 도착정보를 불러오지 못했습니다.');
        }
      })
      .finally(() => {
        if (currentRequest === requestId.current) setLoading(false);
      });
    return () => {
      requestId.current += 1;
    };
  }, [item.route.id, item.routeSetToken, transitSegments.length]);

  if (transitSegments.length === 0) return null;
  const arrivals = new Map(
    (result?.arrivals ?? []).map((arrival) => [arrival.segmentId, arrival]),
  );

  return (
    <div className="map-first__detail-section map-first__transit-arrivals">
      <h4>탑승·도착 안내</h4>
      {loading && <p role="status">선택 경로의 도착정보를 확인하고 있어요.</p>}
      {error && <p role="alert">{error}</p>}
      <ol>
        {transitSegments.map((segment) => {
          const arrival = arrivals.get(segment.id);
          return (
            <li key={segment.id}>
              <strong>{segment.description}</strong>
              {segment.transitDirection && <span>{segment.transitDirection} 방면</span>}
              {arrival && <span>{arrivalLabel(arrival)}</span>}
              {arrival?.status === 'scheduled' && (
                <small>시간표 기준이며 실시간 열차 위치 정보는 아닙니다.</small>
              )}
              {segment.fastBoardingPosition && (
                <span>빠른 환승 승차 위치 {segment.fastBoardingPosition}</span>
              )}
              {(segment.startExitNo || segment.endExitNo) && (
                <span>
                  경로 출입구
                  {segment.startExitNo ? ` 진입 ${segment.startExitNo}번` : ''}
                  {segment.endExitNo ? ` · 하차 ${segment.endExitNo}번` : ''}
                </span>
              )}
              {segment.smartShelterName && (
                <span>{segment.smartShelterName} 스마트쉘터 정류장을 이용하는 경로입니다.</span>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
