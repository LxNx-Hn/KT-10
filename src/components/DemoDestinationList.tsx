import { useAppStore } from '@/store/appStore';
import { findPlace } from '@/data/places';

/** 데모 목적지 버튼(요구사항 §10). 클릭 시 목적지 설정 + 경로 검색. */
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

  const go = (id: string) => {
    const place = findPlace(id);
    if (!place) return;
    setDestination(place);
    ensureOrigin();
    void search();
  };

  return (
    <section className="demodest" aria-label="데모 목적지">
      <h2 className="section-title">데모 목적지</h2>
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
