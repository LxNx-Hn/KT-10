import { useAppStore } from '@/store/appStore';
import RouteList from './RouteList';
import BusArrivalCard from './BusArrivalCard';
import WeatherWarning from './WeatherWarning';
import RouteFeedback from './RouteFeedback';
import FacilityReport from './FacilityReport';

/**
 * 경로 결과 섹션(요구사항 §3). 경로 카드가 지도보다 먼저 보이도록 구성한다.
 * 내부 모델 점수는 정렬에만 사용하고 사용자에게는 경로 특성과 사실을 보여준다.
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
          <RouteFeedback />
          <FacilityReport />
        </>
      )}
    </section>
  );
}
