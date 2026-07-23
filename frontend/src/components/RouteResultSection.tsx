import { useAppStore } from '@/store/appStore';
import RouteList from './RouteList';
import BusArrivalCard from './BusArrivalCard';
import WeatherWarning from './WeatherWarning';
import RouteFeedback from './RouteFeedback';
import FacilityReport from './FacilityReport';
import MapPreviewSection from './MapPreviewSection';

/**
 * 결과가 생기면 활성 경로 지도와 스와이프 카드를 붙여서 보여준다.
 * 지도는 카드 선택과 동기화되고, 부가 정보/후기 폼은 그 아래에 둔다.
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
      {hasResults && <MapPreviewSection />}
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
