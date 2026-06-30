import { useAppStore } from '@/store/appStore';
import { ScoreBar } from './ui';

/**
 * 점수 검증 요약(요구사항 §3 RouteResultSection).
 * 선택된 경로의 8개 하위 점수를 투명하게 노출해 "임의 점수가 아님"을 보여준다.
 */
const LABELS: { key: keyof import('@/types').ScoreComponents; label: string }[] = [
  { key: 'accessibility', label: '접근성' },
  { key: 'walkComfort', label: '보행 편의' },
  { key: 'elevator', label: '승강기' },
  { key: 'lowFloorBus', label: '저상버스' },
  { key: 'weatherSafety', label: '날씨 안전' },
  { key: 'safety', label: '안전성' },
  { key: 'dataReliability', label: '데이터 신뢰도' },
  { key: 'timeEfficiency', label: '시간 효율' },
];

export default function ScoreValidationSummary() {
  const recommendations = useAppStore((s) => s.recommendations);
  const selectedRouteId = useAppStore((s) => s.selectedRouteId);
  const profile = useAppStore((s) => s.profile);

  const target =
    recommendations.find((r) => r.route.id === selectedRouteId) ?? recommendations[0];
  if (!target) return null;

  return (
    <section className="scoreval" aria-label="점수 검증 요약">
      <h2 className="section-title">점수 근거 · 검증</h2>
      <p className="scoreval__meta">
        선택 경로: <b>{target.route.summary}</b> · 프로필 가중치({profile}) 적용 · 최종{' '}
        <b>{Math.round(target.score.finalScore)}점</b>
      </p>
      <div className="scoreval__grid">
        {LABELS.map(({ key, label }) => (
          <ScoreBar key={key} label={label} value={target.score.components[key]} />
        ))}
      </div>
      <p className="scoreval__note">
        모든 하위 점수는 순수 함수로 산출되며, 프로필·날씨·계단·저상버스 시나리오 검증
        테스트로 일관성을 확인합니다(<code>npm run validate</code>).
      </p>
    </section>
  );
}
