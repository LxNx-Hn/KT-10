import { useEffect, useRef, useState, type FormEvent } from 'react';
import { adapters } from '@/adapters';
import { useAppStore } from '@/store/appStore';
import { speak } from '@/voice/synthesis';
import type { BusArrival, BusStopArrivals, Tristate } from '@/types';
import { Badge } from './ui';

function lowFloorBadge(v: Tristate) {
  if (v === true) return <Badge tone="good">저상버스</Badge>;
  if (v === false) return <Badge tone="bad">일반버스</Badge>;
  return null;
}

const etaForSort = (value: number | undefined) => value ?? Number.POSITIVE_INFINITY;

/** 저상버스 우선 정렬: 확정 저상 → 미확인 → 일반, 동일시 빠른 도착 우선 */
function sortLowFloorFirst(arr: BusArrival[]): BusArrival[] {
  const rank = (v: Tristate) => (v === true ? 0 : v === undefined ? 1 : 2);
  return [...arr].sort((a, b) =>
    rank(a.isLowFloor) - rank(b.isLowFloor)
    || etaForSort(a.arrivalMin) - etaForSort(b.arrivalMin));
}

export default function BusArrivalCard() {
  const [stops, setStops] = useState<BusStopArrivals[]>([]);
  const [stopId, setStopId] = useState('');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [searchingStops, setSearchingStops] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [arrivalRefresh, setArrivalRefresh] = useState(0);
  const [error, setError] = useState('');
  const stopSearchRequest = useRef(0);
  const arrivalRequest = useRef(0);
  const lowFloorPriority = useAppStore((s) => s.options.lowFloorPriority);
  const toggleLowFloorPriority = useAppStore((s) => s.toggleLowFloorPriority);

  useEffect(() => {
    if (!stopId || !hasSearched) return;
    const request = ++arrivalRequest.current;
    let active = true;
    setLoading(true);
    setError('');
    void adapters.bus.getArrivals(stopId).then((result) => {
      if (!active || request !== arrivalRequest.current || !result) return;
      setStops((current) => current.map((stop) => (
        stop.stopId === stopId ? result : stop
      )));
    }).catch(() => {
      if (active && request === arrivalRequest.current) {
        setError('실시간 도착 정보를 불러오지 못했습니다.');
      }
    }).finally(() => {
      if (active && request === arrivalRequest.current) setLoading(false);
    });
    return () => { active = false; };
  }, [stopId, hasSearched, arrivalRefresh]);

  const runStopSearch = async () => {
    const request = ++stopSearchRequest.current;
    setSearchingStops(true);
    setHasSearched(true);
    setError('');
    try {
      const results = await adapters.bus.listStops(query);
      if (request !== stopSearchRequest.current) return;
      setStops(results);
      setStopId(results[0]?.stopId ?? '');
      if (!results.length) {
        setError('검색된 정류장이 없습니다.');
        setLoading(false);
      }
    } catch {
      if (request === stopSearchRequest.current) {
        setError('정류장 검색에 실패했습니다.');
      }
    } finally {
      if (request === stopSearchRequest.current) setSearchingStops(false);
    }
  };

  const searchStops = (event: FormEvent) => {
    event.preventDefault();
    void runStopSearch();
  };

  const retryLastAction = () => {
    if (query.trim()) {
      void runStopSearch();
      return;
    }
    if (stopId) {
      setArrivalRefresh((value) => value + 1);
    }
  };

  const current = stops.find((stop) => stop.stopId === stopId);
  const arrivals = current
    ? lowFloorPriority
      ? sortLowFloorFirst(current.arrivals)
      : [...current.arrivals].sort((a, b) => etaForSort(a.arrivalMin) - etaForSort(b.arrivalMin))
    : [];

  const speakArrival = (arrival: BusArrival) => {
    const lowFloorText = arrival.isLowFloor === true
      ? '저상버스입니다'
      : '일반버스입니다';
    const etaPrefix = arrival.arrivalMin !== undefined ? `${arrival.arrivalMin}분 뒤 도착하는 ` : '';
    speak(`${etaPrefix}${arrival.routeName}번 버스는 ${lowFloorText}.`);
  };

  const showInitial = !hasSearched && !loading && !searchingStops;
  const showLoading = searchingStops || loading;
  const showEmptyResult =
    hasSearched
    && !showLoading
    && !error
    && arrivals.length === 0;

  return (
    <section className="bus" aria-label="저상버스 도착 조회">
      <h2 className="section-title">저상버스 도착 조회</h2>

      <form className="bus__search" onSubmit={searchStops}>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="정류소명 또는 5자리 ARS 번호"
          aria-label="버스 정류장 검색"
        />
        <button
          type="submit"
          className="btn btn--ghost"
          disabled={searchingStops || !query.trim()}
        >
          {searchingStops ? '검색 중…' : '검색'}
        </button>
      </form>

      <div className="bus__controls">
        <select
          className="bus__select"
          value={stopId}
          onChange={(event) => {
            setHasSearched(true);
            setStopId(event.target.value);
          }}
          aria-label="정류장 선택"
          disabled={!stops.length}
        >
          {!stops.length && <option value="">정류장을 검색해 주세요</option>}
          {stops.map((stop) => (
            <option key={stop.stopId} value={stop.stopId}>{stop.stopName}</option>
          ))}
        </select>
        <button
          type="button"
          className={`btn btn--toggle ${lowFloorPriority ? 'btn--toggle-on' : ''}`}
          aria-pressed={!!lowFloorPriority}
          onClick={toggleLowFloorPriority}
        >
          ♿ 저상버스 우선 {lowFloorPriority ? 'ON' : 'OFF'}
        </button>
      </div>

      <ul className="bus__list">
        {showInitial && (
          <li className="bus__empty">정류장을 검색하면 도착 정보가 표시돼요.</li>
        )}
        {showEmptyResult && (
          <li className="bus__empty">현재 확인되는 도착 정보가 없어요.</li>
        )}
        {arrivals.map((arrival) => (
          <li
            key={`${arrival.routeName}-${arrival.vehicleNo ?? ''}-${arrival.arrivalMin ?? arrival.arrivalMessage ?? ''}`}
            className="bus__item"
          >
            <span className="bus__route">{arrival.routeName}번</span>
            {arrival.arrivalMin !== undefined && (
              <span className="bus__eta">{arrival.arrivalMin}분 후</span>
            )}
            {lowFloorBadge(arrival.isLowFloor)}
            <button
              type="button"
              className="bus__speak"
              aria-label={`${arrival.routeName}번 버스 도착 음성 안내`}
              onClick={() => speakArrival(arrival)}
            >
              🔊
            </button>
          </li>
        ))}
      </ul>
      {showLoading && <p role="status">도착 정보를 불러오고 있어요.</p>}
      {error && (
        <div className="bus__error" role="alert">
          <p>{error}</p>
          <button type="button" className="btn btn--ghost" onClick={retryLastAction}>
            다시 시도
          </button>
        </div>
      )}
    </section>
  );
}
