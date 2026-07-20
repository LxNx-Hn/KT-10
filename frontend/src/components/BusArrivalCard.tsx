import { useEffect, useState, type FormEvent } from 'react';
import { adapters } from '@/adapters';
import { useAppStore } from '@/store/appStore';
import { speak } from '@/voice/synthesis';
import type { BusArrival, BusStopArrivals, Tristate } from '@/types';
import { Badge } from './ui';

function lowFloorBadge(v: Tristate) {
  if (v === true) return <Badge tone="good">저상버스</Badge>;
  if (v === false) return <Badge tone="bad">일반버스</Badge>;
  return <Badge tone="warn">미확인</Badge>;
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
  const [error, setError] = useState('');
  const lowFloorPriority = useAppStore((s) => s.options.lowFloorPriority);
  const toggleLowFloorPriority = useAppStore((s) => s.toggleLowFloorPriority);

  useEffect(() => {
    void adapters.bus.listStops().then((results) => {
      setStops(results);
      setStopId(results[0]?.stopId ?? '');
    }).catch(() => setError('정류장 목록을 불러오지 못했습니다.'));
  }, []);

  useEffect(() => {
    if (!stopId) return;
    let active = true;
    setLoading(true);
    setError('');
    void adapters.bus.getArrivals(stopId).then((result) => {
      if (!active || !result) return;
      setStops((current) => current.map((stop) => stop.stopId === stopId ? result : stop));
    }).catch(() => {
      if (active) setError('실시간 도착 정보를 불러오지 못했습니다.');
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [stopId]);

  const searchStops = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError('');
    try {
      const results = await adapters.bus.listStops(query);
      setStops(results);
      setStopId(results[0]?.stopId ?? '');
      if (!results.length) setError('검색된 정류장이 없습니다.');
    } catch {
      setError('정류장 검색에 실패했습니다.');
    } finally {
      setLoading(false);
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
      : arrival.isLowFloor === false
        ? '일반버스입니다'
        : '저상버스 여부가 확인되지 않았습니다';
    const eta = arrival.arrivalMin !== undefined
      ? `${arrival.arrivalMin}분 뒤 도착하는`
      : `${arrival.arrivalMessage ?? '도착시각 미확인'} 상태인`;
    speak(`${eta} ${arrival.routeName}번 버스는 ${lowFloorText}.`);
  };

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
        <button type="submit" className="btn" disabled={loading || !query.trim()}>검색</button>
      </form>

      <div className="bus__controls">
        <select className="bus__select" value={stopId} onChange={(event) => setStopId(event.target.value)} aria-label="정류장 선택">
          {!stops.length && <option value="">정류장을 검색해 주세요</option>}
          {stops.map((stop) => <option key={stop.stopId} value={stop.stopId}>{stop.stopName}</option>)}
        </select>
        <button type="button" className={`btn btn--toggle ${lowFloorPriority ? 'btn--toggle-on' : ''}`} aria-pressed={!!lowFloorPriority} onClick={toggleLowFloorPriority}>
          ♿ 저상버스 우선 {lowFloorPriority ? 'ON' : 'OFF'}
        </button>
      </div>

      <ul className="bus__list">
        {!loading && arrivals.length === 0 && <li className="bus__empty">도착 정보가 없습니다.</li>}
        {arrivals.map((arrival) => (
          <li key={`${arrival.routeName}-${arrival.vehicleNo ?? ''}-${arrival.arrivalMin ?? arrival.arrivalMessage ?? ''}`} className="bus__item">
            <span className="bus__route">{arrival.routeName}번</span>
            <span className="bus__eta">{arrival.arrivalMin !== undefined ? `${arrival.arrivalMin}분 후` : (arrival.arrivalMessage ?? '도착시각 미확인')}</span>
            {lowFloorBadge(arrival.isLowFloor)}
            <button type="button" className="bus__speak" aria-label={`${arrival.routeName}번 버스 도착 음성 안내`} onClick={() => speakArrival(arrival)}>🔊</button>
          </li>
        ))}
      </ul>
      {loading && <p role="status">버스 정보를 불러오는 중입니다.</p>}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
