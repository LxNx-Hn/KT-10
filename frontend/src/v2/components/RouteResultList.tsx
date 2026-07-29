import { useMemo } from 'react';
import { routeRefinementKey } from '@/store/appStore';
import type { ProfileId, ScoredRoute } from '@/types';
import { serverRankedRecommendations } from '@/utils/routes';
import {
  ROUTE_SCORE_DISCLAIMER,
  buildRouteViewModel,
} from '../routeViewModel';
import RouteSummaryCard from './RouteSummaryCard';

export default function RouteResultList({
  recommendations,
  profile,
  selectedRouteId,
  refiningRouteKeys,
  onSelectRoute,
  onDetails,
}: {
  recommendations: ScoredRoute[];
  profile: ProfileId;
  selectedRouteId: string | null;
  refiningRouteKeys: string[];
  onSelectRoute: (routeId: string) => void;
  onDetails: () => void;
}) {
  const ranked = useMemo(
    () => serverRankedRecommendations(recommendations),
    [recommendations],
  );
  const views = useMemo(
    () =>
      ranked.map((item, index) => ({
        item,
        view: buildRouteViewModel(item, index + 1, profile),
      })),
    [profile, ranked],
  );
  const selectedIndex = views.findIndex(
    ({ view }) => view.routeId === selectedRouteId,
  );
  const activeIndex = selectedIndex >= 0 ? selectedIndex : null;

  return (
    <section className="map-first__route-list" aria-label="적합 점수순 비교 경로">
      <div className="map-first__route-list-heading">
        <div>
          <h2>추천 경로 {views.length}개</h2>
          <p>위아래로 스크롤해 다른 길의 특성과 적합 점수를 비교하세요.</p>
        </div>
        <output aria-live="polite">
          <strong>{activeIndex === null ? '–' : activeIndex + 1}</strong> / {views.length}
        </output>
      </div>

      <div
        className="map-first__route-stack"
        role="list"
        aria-label="점수순 경로 카드"
      >
        {views.map(({ item, view }) => (
          <RouteSummaryCard
            key={view.routeId}
            view={view}
            selected={view.routeId === selectedRouteId}
            refining={Boolean(
              item.routeSetToken
              && refiningRouteKeys.includes(
                routeRefinementKey(item.routeSetToken, view.routeId),
              )
            )}
            onSelect={() => onSelectRoute(view.routeId)}
            onDetails={() => {
              onSelectRoute(view.routeId);
              onDetails();
            }}
          />
        ))}
      </div>
      <p className="map-first__score-note">{ROUTE_SCORE_DISCLAIMER}</p>
    </section>
  );
}
