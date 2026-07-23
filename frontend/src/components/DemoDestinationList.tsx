import { useAppStore } from '@/store/appStore';
import { findPlace } from '@/data/places';

/** 부산 주요 목적지 바로가기. 출발지가 있으면 즉시 검색하고, 없으면 위치를 요청한다. */
const DEMO_DESTS = [
  { id: 'seomyeon-stn', label: '서면역' },
  { id: 'gu-office', label: '부산진구청' },
  { id: 'bujeon-stn', label: '부전역' },
  { id: 'jeonpo-stn', label: '전포역' },
];

export default function DemoDestinationList() {
  const setDestination = useAppStore((s) => s.setDestination);
  const ensureOrigin = useAppStore((s) => s.ensureOrigin);
  const search = useAppStore((s) => s.search);
  const origin = useAppStore((s) => s.origin);

  const go = (id: string) => {
    const place = findPlace(id);
    if (!place) return;
    setDestination(place);
    if (origin) {
      void search();
    } else {
      ensureOrigin();
    }
  };

  return (
    <section className="demodest" aria-label="주요 목적지">
      <h2 className="section-title">주요 목적지</h2>
      <div className="demodest__row">
        {DEMO_DESTS.map((d) => (
          <button key={d.id} type="button" className="demodest__btn" onClick={() => go(d.id)}>
            📍 {d.label}
          </button>
        ))}
      </div>
    </section>
  );
}
