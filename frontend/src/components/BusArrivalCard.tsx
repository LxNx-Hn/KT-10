import { useEffect, useState } from 'react';
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

/** 저상버스 우선 정렬: 확정 저상 → 미확인 → 일반, 동일시 빠른 도착 우선 */
function sortLowFloorFirst(arr: BusArrival[]): BusArrival[] {
  const rank = (v: Tristate) => (v === true ? 0 : v === undefined ? 1 : 2);
  return [...arr].sort((a, b) => rank(a.isLowFloor) - rank(b.isLowFloor) || a.arrivalMin - b.arrivalMin);
}

export default function BusArrivalCard() {
  const [stops, setStops] = useState<BusStopArrivals[]>([]);
  const [stopId, setStopId] = useState<string>('');
  const lowFloorPriority = useAppStore((s) => s.options.lowFloorPriority);
  const toggleLowFloorPriority = useAppStore((s) => s.toggleLowFloorPriority);

  useEffect(() => {
    void adapters.bus.listStops().then((s) => {
      setStops(s);
      setStopId(s[0]?.stopId ?? '');
    });
  }, []);

  const current = stops.find((s) => s.stopId === stopId);
  const arrivals = current
    ? lowFloorPriority
      ? sortLowFloorFirst(current.arrivals)
      : [...current.arrivals].sort((a, b) => a.arrivalMin - b.arrivalMin)
    : [];

  const speakArrival = (a: BusArrival) => {
    const lf =
      a.isLowFloor === true
        ? '저상버스입니다'
        : a.isLowFloor === false
          ? '일반버스입니다'
          : '저상버스 여부가 확인되지 않았습니다';
    speak(`${a.arrivalMin}분 뒤 도착하는 ${a.routeName}번 버스는 ${lf}.`);
  };

  return (
    <section className="bus" aria-label="저상버스 도착 조회">
      <h2 className="section-title">저상버스 도착 조회</h2>

      <div className="bus__controls">
        <select
          className="bus__select"
          value={stopId}
          onChange={(e) => setStopId(e.target.value)}
          aria-label="정류장 선택"
        >
          {stops.map((s) => (
            <option key={s.stopId} value={s.stopId}>
              {s.stopName}
            </option>
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
        {arrivals.length === 0 && <li className="bus__empty">도착 정보가 없습니다.</li>}
        {arrivals.map((a) => (
          <li key={a.routeName} className="bus__item">
            <span className="bus__route">{a.routeName}번</span>
            <span className="bus__eta">{a.arrivalMin}분 후</span>
            {lowFloorBadge(a.isLowFloor)}
            <button
              type="button"
              className="bus__speak"
              aria-label={`${a.routeName}번 버스 도착 음성 안내`}
              onClick={() => speakArrival(a)}
            >
              🔊
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
