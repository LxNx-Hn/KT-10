import { useAppStore } from '@/store/appStore';

/** 저장 프로필과 달리, 매번 바뀌는 이동 조건은 검색 화면에서 즉시 조정한다. */
export default function RouteConditions() {
  const options = useAppStore((s) => s.options);
  const toggleCarryLuggage = useAppStore((s) => s.toggleCarryLuggage);
  const enableStairAvoidance = useAppStore((s) => s.enableStairAvoidance);

  return (
    <section className="route-conditions" aria-label="이번 이동 조건">
      <h2 className="section-title">이번 이동 조건</h2>
      <p className="route-conditions__hint">자주 달라지는 조건은 여기서 바로 바꿀 수 있어요.</p>
      <div className="route-conditions__buttons">
        <button type="button" className={`condition-chip ${options.carryLuggage ? 'condition-chip--active' : ''}`} aria-pressed={Boolean(options.carryLuggage)} onClick={toggleCarryLuggage}>
          🧳 짐 많음
        </button>
        <button type="button" className={`condition-chip ${options.avoidStairs ? 'condition-chip--active' : ''}`} aria-pressed={Boolean(options.avoidStairs)} onClick={enableStairAvoidance}>
          🚫 계단 회피
        </button>
      </div>
    </section>
  );
}
