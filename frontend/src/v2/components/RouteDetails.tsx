import { useMemo } from 'react';
import type { ProfileId, ScoredRoute } from '@/types';
import {
  buildRouteViewModel,
  formatRouteSourceLabel,
  routeScoreDisclaimer,
  type V2RouteFactKind,
} from '../routeViewModel';

const FACT_KIND_LABEL: Record<V2RouteFactKind, string> = {
  advantage: '확인된 장점',
  caution: '주의',
  estimate: '추정',
  neutral: '정보',
  unknown: '확인 필요',
};

export default function RouteDetails({
  item,
  rank,
  profile,
  peers,
}: {
  item: ScoredRoute;
  rank: number;
  profile: ProfileId;
  peers?: ScoredRoute[];
}) {
  const view = useMemo(
    () => buildRouteViewModel(item, rank, profile, peers ?? [item]),
    [item, peers, profile, rank],
  );
  const sources = item.route.sources ?? [];
  const scoreNote = routeScoreDisclaimer(peers && peers.length > 0 ? peers.length : 1);

  return (
    <section className="map-first__route-detail" aria-label="선택 경로 상세">
      <div className="map-first__route-detail-title">
        <div>
          <p>{view.title}</p>
          <h3>{view.summary}</h3>
        </div>
        <div
          className="map-first__route-score"
          title={view.score.ariaLabel}
          aria-label={view.score.ariaLabel}
        >
          {view.score.available && view.score.rounded !== null ? (
            <>
              <small>{view.scoreKindLabel}</small>
              <strong>{view.score.rounded}</strong>
              <span>점</span>
            </>
          ) : (
            <small className="map-first__route-score-unavailable">
              {view.score.summaryLabel}
            </small>
          )}
        </div>
      </div>
      <p className="map-first__score-note">{scoreNote}</p>

      <dl className="map-first__fact-list">
        {view.facts.map((fact) => (
          <div key={`${fact.id}-${fact.label}`}>
            <dt>
              <span className={`map-first__fact-kind map-first__fact-kind--${fact.kind}`}>
                {FACT_KIND_LABEL[fact.kind]}
              </span>
              {fact.label}
            </dt>
            {fact.detail && <dd>{fact.detail}</dd>}
          </div>
        ))}
      </dl>

      {view.reasons.length > 0 && (
        <div className="map-first__detail-section">
          <h4>이 경로의 특징</h4>
          <ul>{view.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
        </div>
      )}
      {view.cautions.length > 0 && (
        <div className="map-first__detail-section map-first__detail-section--warn">
          <h4>주의사항</h4>
          <ul>{view.cautions.map((caution) => <li key={caution}>{caution}</li>)}</ul>
        </div>
      )}
      {view.needsConfirmation.length > 0 && (
        <div className="map-first__detail-section">
          <h4>확인 필요한 정보</h4>
          <ul>
            {view.needsConfirmation.map((label) => <li key={label}>{label}</li>)}
          </ul>
        </div>
      )}
      <div className="map-first__detail-section">
        <h4>경로 데이터</h4>
        <p>
          지도 선 품질: {item.route.geometryQuality === 'exact'
            ? '실제 경로 형상'
            : item.route.geometryQuality === 'mixed'
              ? '주 경로·연결 경로 포함'
              : item.route.geometryQuality === 'estimated'
                ? '보행 연결 경로'
                : '공공 보행 경로'}
        </p>
        {sources.length > 0 ? (
          <ul>
            {sources.map((source) => (
              <li key={source}>{formatRouteSourceLabel(source)}</li>
            ))}
          </ul>
        ) : (
          <p>공공 보행 경로망 데이터 기준</p>
        )}
      </div>
    </section>
  );
}
