import { useMemo } from 'react';
import type { ProfileId, ScoredRoute } from '@/types';
import {
  buildRouteViewModel,
  formatRouteSourceLabel,
  routeScoreDisclaimer,
  type V2RouteFact,
  type V2RouteFactKind,
} from '../routeViewModel';
import {
  formatSlopePercent,
  resolvePeakSlopePercent,
} from '../utils/slopeLevel';
import TransitArrivalPanel from './TransitArrivalPanel';

const FACT_KIND_LABEL: Record<V2RouteFactKind, string> = {
  advantage: '확인된 장점',
  caution: '주의',
  estimate: '추정',
  neutral: '정보',
  unknown: '확인 필요',
};

function geometryQualityMessage(
  quality: ScoredRoute['route']['geometryQuality'],
): string | null {
  if (quality === 'exact') {
    return '실제 이동 경로를 기준으로 안내해요.';
  }
  if (quality === 'mixed') {
    return '주요 구간과 보행 연결 구간을 함께 안내해요.';
  }
  if (quality === 'estimated') {
    return '보행 연결 구간을 기준으로 안내해요.';
  }
  return null;
}

function FactRow({ fact }: { fact: V2RouteFact }) {
  return (
    <div>
      <dt>
        {fact.kind !== 'estimate' && (
          <span className={`map-first__fact-kind map-first__fact-kind--${fact.kind}`}>
            {FACT_KIND_LABEL[fact.kind]}
          </span>
        )}
        {fact.label}
      </dt>
    </div>
  );
}

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
  const terrain = item.route.terrain;
  const terrainReady =
    terrain?.status === 'estimated_90m'
    && terrain.avgSlopePercent !== undefined;
  const avgSlopeText = terrainReady
    ? formatSlopePercent(terrain.avgSlopePercent)
    : null;
  const peakSlope = terrainReady
    ? resolvePeakSlopePercent(terrain.maxSlopePercent, terrain.minSlopePercent)
    : null;
  const peakSlopeText =
    peakSlope === null ? null : formatSlopePercent(peakSlope);
  const elevationGainM =
    terrainReady
    && terrain.elevationGainM !== undefined
    && terrain.elevationGainM > 0
      ? Math.round(terrain.elevationGainM)
      : null;

  const featureFacts = view.facts.filter(
    (fact) => fact.id !== 'terrain' && fact.id !== 'elevation-gain',
  );
  const technicalSourceLines = [
    terrain?.source,
    item.route.shade?.source,
  ].filter((value): value is string => Boolean(value && value.trim()));
  const geometryMessage = geometryQualityMessage(item.route.geometryQuality);

  return (
    <section className="map-first__route-detail" aria-label="선택 경로 상세">
      <div className="map-first__route-detail-header">
        <p className="map-first__route-detail-rank">{view.title}</p>
        {view.score.available && view.score.rounded !== null ? (
          <p
            className="map-first__route-detail-fit"
            title={view.score.ariaLabel}
            aria-label={view.score.ariaLabel}
          >
            {view.score.summaryLabel}
          </p>
        ) : (
          <p
            className="map-first__route-detail-fit map-first__route-detail-fit--unavailable"
            aria-label={view.score.ariaLabel}
          >
            {view.score.summaryLabel}
          </p>
        )}
        <h3 className="map-first__route-detail-name">{view.summary}</h3>
        <p className="map-first__route-detail-meta">{view.meta}</p>
        <p className="map-first__score-note">{scoreNote}</p>
      </div>

      <TransitArrivalPanel item={item} />

      {avgSlopeText !== null && (
        <div className="map-first__detail-section map-first__detail-section--terrain">
          <h4>경사 정보</h4>
          <dl className="map-first__terrain-list">
            <div>
              <dt>보행구간 평균 경사</dt>
              <dd>{avgSlopeText}%</dd>
            </div>
            {peakSlopeText !== null && (
              <div>
                <dt>최대 경사</dt>
                <dd>{peakSlopeText}%</dd>
              </div>
            )}
            {elevationGainM !== null && (
              <div>
                <dt>누적 오르막</dt>
                <dd>{elevationGainM}m</dd>
              </div>
            )}
          </dl>
          <p className="map-first__terrain-note">
            고도 데이터를 바탕으로 계산한 예상치예요.
          </p>
        </div>
      )}

      {(view.reasons.length > 0 || featureFacts.length > 0) && (
        <div className="map-first__detail-section">
          <h4>이 경로의 특징</h4>
          {featureFacts.length > 0 && (
            <dl className="map-first__fact-list map-first__fact-list--compact">
              {featureFacts.map((fact) => (
                <FactRow key={`${fact.id}-${fact.label}`} fact={fact} />
              ))}
            </dl>
          )}
          {view.reasons.length > 0 && (
            <ul>{view.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
          )}
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

      <div className="map-first__detail-section map-first__detail-section--sources">
        <h4>데이터 출처</h4>
        {geometryMessage && <p>{geometryMessage}</p>}
        {sources.length > 0 ? (
          <ul>
            {sources.map((source) => (
              <li key={source}>{formatRouteSourceLabel(source)}</li>
            ))}
          </ul>
        ) : (
          <p>공공 보행 경로망 데이터 기준</p>
        )}
        {technicalSourceLines.length > 0 && (
          <ul className="map-first__source-tech">
            {technicalSourceLines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
