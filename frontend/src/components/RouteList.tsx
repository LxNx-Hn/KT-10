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
    <section className="route-list" aria-label="추천 경로 3개">
      <h2 className="section-title">추천 경로 {recommendations.length}개</h2>
      {recommendations.map((item, i) => (
        <RouteCard key={item.route.id} item={item} rank={i + 1} />
      ))}
    </section>
  );
}
