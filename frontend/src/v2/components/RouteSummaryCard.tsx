import {
  type V2RouteFact,
  type V2RouteViewModel,
} from '../routeViewModel';

const ATTENTION_FACT_IDS = new Set([
  'terrain',
  'stairs',
  'elevator',
  'low-floor',
  'shade',
]);

/** 추천 근거 문장과 겹치는 배지 라벨은 숨긴다. */
function overlapsReason(label: string, reasons: string[]): boolean {
  const compact = label.replace(/\s+/g, '');
  return reasons.some((reason) => {
    const text = reason.replace(/\s+/g, '');
    return text.includes(compact) || compact.includes(text.slice(0, 8));
  });
}

function pickAttentionFacts(
  facts: V2RouteFact[],
  reasons: string[],
): V2RouteFact[] {
  return facts
    .filter((fact) => ATTENTION_FACT_IDS.has(fact.id))
    .filter((fact) => fact.kind !== 'neutral')
    .filter((fact) => !overlapsReason(fact.label, reasons))
    .slice(0, 3);
}

export default function RouteSummaryCard({
  view,
  selected,
  refining,
  onSelect,
  onDetails,
}: {
  view: V2RouteViewModel;
  selected: boolean;
  refining: boolean;
  onSelect: () => void;
  onDetails: () => void;
}) {
  const displayReasons = view.reasons.slice(0, 3);
  const attentionFacts = pickAttentionFacts(view.facts, displayReasons);
  const durationLabel = `${view.stats.durationMin}분`;
  const scoreText = view.score.available && view.score.rounded !== null
    ? `${view.scoreKindLabel} ${view.score.rounded}점`
    : view.score.summaryLabel;

  return (
    <article
      className={`map-first__route-card${
        selected ? ' map-first__route-card--selected' : ''
      }`}
      role="listitem"
      tabIndex={0}
      data-route-id={view.routeId}
      aria-current={selected ? 'true' : undefined}
      aria-busy={refining ? 'true' : undefined}
      aria-label={`${view.rank}순위 경로, 소요 ${durationLabel}, ${view.score.ariaLabel}`}
      onClick={onSelect}
      onKeyDown={(event) => {
        // Tab으로 focus만 옮기는 것은 선택이 아니다. 키보드 선택은
        // Enter·Space에서만 명시적으로 처리한다.
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onSelect();
        }
      }}
    >
      <div className="map-first__route-card-topline">
        <span className="map-first__rank-badge">{view.rank}순위</span>
        <span className="map-first__route-card-type">
          {view.profileLabel}
          {' '}
          맞춤
        </span>
      </div>

      <h3 className="map-first__route-card-summary">{view.summary}</h3>

      <div className="map-first__route-card-metrics">
        <p
          className="map-first__route-card-duration"
          aria-label={`소요시간 ${durationLabel}`}
        >
          <strong>{view.stats.durationMin}</strong>
          <span>분</span>
        </p>
        <div
          className="map-first__route-score"
          title={view.score.ariaLabel}
          aria-label={view.score.ariaLabel}
        >
          {view.score.available && view.score.rounded !== null ? (
            <span className="map-first__route-score-text">{scoreText}</span>
          ) : (
            <span className="map-first__route-score-unavailable">
              {view.score.summaryLabel}
            </span>
          )}
        </div>
      </div>

      <ul className="map-first__route-stats" aria-label="경로 요약">
        <li>
          <strong>{view.stats.walkM}</strong>
          <span>m 도보</span>
        </li>
        <li>
          <strong>{view.stats.transferCount}</strong>
          <span>회 환승</span>
        </li>
      </ul>

      {displayReasons.length > 0 && (
        <ul className="map-first__route-card-reasons" aria-label="추천 근거">
          {displayReasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}

      {attentionFacts.length > 0 && (
        <div className="map-first__badges" aria-label="경사·접근성 정보">
          {attentionFacts.map((fact) => (
            <span
              key={fact.id}
              className={[
                'map-first__badge',
                `map-first__badge--${fact.kind}`,
                fact.slopeLevel
                  ? `map-first__badge--slope-${fact.slopeLevel}`
                  : '',
              ]
                .filter(Boolean)
                .join(' ')}
              {...(fact.slopeLevel && fact.title
                ? { title: fact.title, 'aria-label': fact.title }
                : {})}
            >
              {fact.label}
            </span>
          ))}
        </div>
      )}

      <button
        type="button"
        className="map-first__sheet-cta"
        onClick={(event) => {
          event.stopPropagation();
          onDetails();
        }}
      >
        상세 정보 보기
      </button>
    </article>
  );
}
