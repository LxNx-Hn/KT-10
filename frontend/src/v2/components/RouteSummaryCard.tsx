import {
  type V2RouteFact,
  type V2RouteViewModel,
  type V2TransitStep,
} from '../routeViewModel';
import { formatDurationMin } from '@/utils/formatDurationMin';

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

function TransitModeIcon({ mode }: { mode: V2TransitStep['mode'] }) {
  if (mode === 'walk') {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="13" cy="4.5" r="2" />
        <path d="m11 8-2 5 3 2 1.5 5M11 8l4 3 2 4M9 13l-3 5" />
      </svg>
    );
  }
  if (mode === 'bus') {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect x="5" y="3" width="14" height="15" rx="3" />
        <path d="M7.5 7h9M8 13h.01M16 13h.01M8 18v2M16 18v2" />
      </svg>
    );
  }
  if (mode === 'subway') {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect x="6" y="3" width="12" height="15" rx="4" />
        <path d="M8.5 8h7M9 13h.01M15 13h.01M9 18l-2 3M15 18l2 3" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 8h12l-3-3M19 16H7l3 3" />
    </svg>
  );
}

function TransitSequence({ steps }: { steps: V2TransitStep[] }) {
  if (steps.length === 0) return null;
  return (
    <ol className="map-first__route-card-transit" aria-label="이동 수단 순서">
      {steps.map((step) => {
        const accessibleLabel = [
          step.modeLabel,
          step.routeLabel,
          `${step.durationMin}분`,
        ]
          .filter(Boolean)
          .join(' ');
        return (
          <li
            key={step.id}
            data-mode={step.mode}
            data-subway-line={step.subwayLineId}
            aria-label={accessibleLabel}
          >
            <span className="map-first__transit-icon">
              <TransitModeIcon mode={step.mode} />
            </span>
            <span className="map-first__transit-mode">{step.modeLabel}</span>
            {step.routeLabel && (
              <span className="map-first__transit-route">{step.routeLabel}</span>
            )}
            <span className="map-first__transit-duration">
              {step.durationMin}
              분
            </span>
          </li>
        );
      })}
    </ol>
  );
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
  const reasonHighlights = (
    view.reasonHighlights.length > 0
      ? view.reasonHighlights
      : displayReasons
  ).slice(0, 3);
  const attentionFacts = pickAttentionFacts(view.facts, displayReasons);
  const durationLabel = formatDurationMin(view.stats.durationMin);
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
      aria-label={`${view.rank}순위 경로, 소요 ${durationLabel}, ${reasonHighlights.join(', ')}, ${view.score.ariaLabel}`}
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
      {/* 상단: 순위 · 이동수단/경로명 · 소요시간(지표 행) */}
      <div className="map-first__route-card-header">
        <div className="map-first__route-card-topline">
          <span className="map-first__rank-badge">{view.rank}순위</span>
          <span className="map-first__route-card-type">
            {view.profileLabel}
            {' '}
            맞춤
          </span>
          <h3 className="map-first__route-card-summary">{view.summary}</h3>
        </div>

        <TransitSequence steps={view.transitSteps} />

        {reasonHighlights.length > 0 && (
          <ul
            className="map-first__route-card-reasons"
            aria-label="추천 근거"
          >
            {reasonHighlights.map((label, index) => (
              <li key={`${label}-${index}`} title={displayReasons[index]}>
                {label}
              </li>
            ))}
          </ul>
        )}

        <div className="map-first__route-card-metrics">
          <p
            className="map-first__route-card-duration"
            aria-label={`소요시간 ${durationLabel}`}
          >
            <strong>{durationLabel}</strong>
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
      </div>

      {/* 중단: 도보 · 환승 · 핵심 특성 */}
      <div className="map-first__route-card-body">
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
      </div>

      {/* 하단: 상세 보조 액션 (본문 위에 겹치지 않음) */}
      <button
        type="button"
        className="map-first__sheet-cta map-first__route-card-cta"
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
