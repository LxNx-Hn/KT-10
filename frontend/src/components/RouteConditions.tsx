import { useAppStore, type ToggleableScoringOption } from '@/store/appStore';

const CONDITIONS: Array<{
  key: ToggleableScoringOption;
  icon: string;
  label: string;
}> = [
  { key: 'carryLuggage', icon: '🧳', label: '짐 많음' },
  { key: 'stroller', icon: '🛞', label: '유아차 이용' },
  { key: 'avoidStairs', icon: '🚫', label: '계단 회피' },
  { key: 'shadePriority', icon: '🏢', label: '건물 그늘 우선' },
  { key: 'lowFloorPriority', icon: '🚌', label: '저상버스 우선' },
  { key: 'minimizeTransfers', icon: '↔️', label: '환승 최소' },
];

function localDateTimeAt(hour: number): string {
  const date = new Date();
  date.setHours(hour, 0, 0, 0);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}T${String(hour).padStart(2, '0')}:00`;
}

function localDateTimeNow(): string {
  const date = new Date();
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hour = String(date.getHours()).padStart(2, '0');
  const minute = String(date.getMinutes()).padStart(2, '0');
  return `${year}-${month}-${day}T${hour}:${minute}`;
}

/** 저장 프로필과 달리, 매번 바뀌는 이동 조건은 검색 화면에서 즉시 조정한다. */
export default function RouteConditions() {
  const options = useAppStore((s) => s.options);
  const setScoringOption = useAppStore((s) => s.setScoringOption);
  const setDepartureAt = useAppStore((s) => s.setDepartureAt);

  return (
    <section className="route-conditions" aria-label="이번 이동 조건">
      <h2 className="section-title">이번 이동 조건</h2>
      <p className="route-conditions__hint">자주 달라지는 조건은 여기서 바로 바꿀 수 있어요.</p>
      <label className="route-conditions__time">
        <span>건물 그늘 계산 시각</span>
        <input
          type="datetime-local"
          value={options.departureAt ?? ''}
          onChange={(event) => setDepartureAt(event.target.value)}
        />
      </label>
      <div className="route-conditions__time-presets" aria-label="그늘 계산 시각 바로 선택">
        <button type="button" onClick={() => setDepartureAt(localDateTimeNow())}>지금</button>
        <button type="button" onClick={() => setDepartureAt(localDateTimeAt(9))}>오전 9시</button>
        <button type="button" onClick={() => setDepartureAt(localDateTimeAt(14))}>오후 2시</button>
        <button type="button" onClick={() => setDepartureAt(localDateTimeAt(18))}>오후 6시</button>
      </div>
      <p className="route-conditions__shade-note">
        그늘은 건물 도형·높이와 태양 위치로 계산합니다. 나무 그늘은 포함하지 않으며,
        확인되지 않은 특성은 점수에서 제외합니다.
      </p>
      <div className="route-conditions__buttons">
        {CONDITIONS.map(({ key, icon, label }) => {
          const active = Boolean(options[key]);
          return (
            <button
              key={key}
              type="button"
              className={`condition-chip ${active ? 'condition-chip--active' : ''}`}
              aria-pressed={active}
              onClick={() => setScoringOption(key, !active)}
            >
              <span aria-hidden="true">{icon}</span> {label}
            </button>
          );
        })}
      </div>
    </section>
  );
}
