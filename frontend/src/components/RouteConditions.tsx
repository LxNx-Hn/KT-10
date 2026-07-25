import { useAppStore, type ToggleableScoringOption } from '@/store/appStore';

const CONDITIONS: Array<{
  key: ToggleableScoringOption;
  icon: string;
  label: string;
}> = [
  { key: 'stroller', icon: '🛞', label: '유아차 이용' },
  { key: 'shadePriority', icon: '🏢', label: '건물 그늘 우선' },
  { key: 'lowFloorPriority', icon: '🚌', label: '저상버스 우선' },
  { key: 'minimizeTransfers', icon: '↔️', label: '환승 최소' },
];

export const ROUTE_CONDITION_KEYS = CONDITIONS.map(({ key }) => key);

/** 저장 프로필과 달리, 매번 바뀌는 이동 조건은 검색 화면에서 즉시 조정한다. */
export default function RouteConditions() {
  const options = useAppStore((s) => s.options);
  const setScoringOption = useAppStore((s) => s.setScoringOption);

  return (
    <section className="route-conditions" aria-label="이번 이동 조건">
      <h2 className="section-title">이번 이동 조건</h2>
      <p className="route-conditions__hint">
        상단 빠른 조건 외에 필요한 항목을 여기서 바꿀 수 있어요.
      </p>
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
