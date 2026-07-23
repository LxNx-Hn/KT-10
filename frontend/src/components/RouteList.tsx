import { useAppStore } from '@/store/appStore';
import RouteCard from './RouteCard';

export default function RouteList() {
  const recommendations = useAppStore((s) => s.recommendations);
  const error = useAppStore((s) => s.error);
  const loading = useAppStore((s) => s.loading);

  if (error) return <p className="notice notice--error">{error}</p>;
  if (loading) return <p className="notice">경로를 평가하고 있어요…</p>;
  if (recommendations.length === 0)
    return (
      <p className="notice">
        출발지·도착지·프로필을 선택하고 <b>경로 찾기</b>를 눌러 주세요.
      </p>
    );

  return (
    <section className="route-list" aria-label="규칙 기반 비교 경로">
      <h2 className="section-title">비교 경로 {recommendations.length}개</h2>
      <p className="route-list__hint">
        제일 빠른 길·경사도 적은 길·그늘 많은 길을 먼저 보여주고, 점수는 비교 보조값으로 사용합니다.
      </p>
      {recommendations.map((item, i) => (
        <RouteCard key={item.route.id} item={item} rank={i + 1} />
      ))}
    </section>
  );
}
