import { useMemo } from 'react';
import { routeRefinementKey } from '@/store/appStore';
import type { ProfileId, ScoredRoute } from '@/types';
import { serverRankedRecommendations } from '@/utils/routes';
import {
  buildRouteViewModel,
  routeScoreDisclaimer,
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
    () => serverRankedRecommendations(recommendations ?? []),
    [recommendations],
  );
  const views = useMemo(
    () =>
      ranked.map((item, index) => ({
        item,
        view: buildRouteViewModel(item, index + 1, profile, ranked),
      })),
    [profile, ranked],
  );
  const selectedIndex = views.findIndex(
    ({ view }) => view.routeId === selectedRouteId,
  );
  const activeIndex = selectedIndex >= 0 ? selectedIndex : null;
  const routeCount = views.length;
  const listLabel =
    routeCount > 1 ? '맞춤 적합도순 비교 경로' : '추천 경로';
  const heading =
    routeCount === 1
      ? '경로 1개를 찾았어요'
      : `경로 ${routeCount}개를 찾았어요`;

  return (
    <section className="map-first__route-list" aria-label={listLabel}>
      <div className="map-first__route-list-heading">
        <div>
          <h2>{heading}</h2>
          {routeCount > 1 && (
            <p>위아래로 스크롤해 다른 길을 비교하세요.</p>
          )}
        </div>
        {routeCount > 1 && (
          <output aria-live="polite" aria-label={`선택 경로 ${activeIndex === null ? '없음' : activeIndex + 1}, 전체 ${routeCount}`}>
            <strong>{activeIndex === null ? '–' : activeIndex + 1}</strong>
            {' '}
            /
            {' '}
            {routeCount}
          </output>
        )}
      </div>

      <p className="map-first__score-note map-first__score-note--list">
        {routeScoreDisclaimer(routeCount)}
      </p>

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
    </section>
  );
}
