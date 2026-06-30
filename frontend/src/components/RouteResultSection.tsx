import { useAppStore } from '@/store/appStore';
import RouteList from './RouteList';
import BusArrivalCard from './BusArrivalCard';
import WeatherWarning from './WeatherWarning';
import ScoreValidationSummary from './ScoreValidationSummary';

/**
 * 경로 결과 섹션(요구사항 §3). 경로 카드가 지도보다 먼저 보이도록 구성한다.
 * 순서: RouteCards → WeatherWarning → LowFloorBusInfo → ScoreValidationSummary.
 */
export default function RouteResultSection() {
  const recommendations = useAppStore((s) => s.recommendations);
  const loading = useAppStore((s) => s.loading);
  const error = useAppStore((s) => s.error);
  const hasResults = recommendations.length > 0;

  // 결과/로딩/에러가 없으면 섹션 자체를 숨긴다(검색 전 홈 화면 유지).
  if (!hasResults && !loading && !error) return null;

  return (
    <section className="results" aria-label="경로 결과">
      <RouteList />
      {hasResults && (
        <>
          <WeatherWarning />
          <BusArrivalCard />
          <ScoreValidationSummary />
        </>
      )}
    </section>
  );
}
