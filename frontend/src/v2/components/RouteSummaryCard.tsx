import {
  type V2RouteFact,
  type V2RouteViewModel,
  type V2TransitStep,
} from '../routeViewModel';
import { formatRouteTransitTitle } from '../formatRouteTransitTitle';
import { formatDurationMin } from '@/utils/formatDurationMin';

export { formatRouteTransitTitle, formatRouteCardTitle } from '../formatRouteTransitTitle';

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

/**
 * 도보는 지도에서 차콜 실선으로 그려진다. 화면을 보지 않는 사용자가 카드와
 * 지도를 연결할 수 있도록 색 설명을 함께 읽어준다. 경사 오버레이를 켜면
 * 도보선이 경사 등급색으로 바뀌지만, 카드는 지도 토글 상태를 알 수 없으므로
 * 기본 상태를 기준으로 안내한다.
 */
function transitAccessibleLabel(step: V2TransitStep): string {
  if (step.mode === 'transfer') return '환승';
  return [
    step.modeLabel,
    step.mode === 'walk' ? '지도에서 회색 선' : null,
    step.routeLabel,
    `${step.durationMin}분`,
  ]
    .filter(Boolean)
    .join(' ');
}

/**
 * bar 시각 라벨은 duration만. routeLabel은 title·aria에 둔다.
 * 가독성(아이콘+N분)을 duration 비율보다 우선한다.
 */
function segmentFlexGrow(step: V2TransitStep, compact: boolean): number {
  const base = Math.max(step.durationMin, 1);
  // compact에서도 짧은 walk가 찌그러지지 않도록 floor 유지
  return compact ? Math.max(base, 4) : base;
}

const TRANSIT_BAR_MODES = new Set<V2TransitStep['mode']>([
  'bus',
  'subway',
  'train',
  'express_bus',
  'ferry',
  'airplane',
]);

function isTransitBarMode(mode: V2TransitStep['mode']): boolean {
  return TRANSIT_BAR_MODES.has(mode);
}

/**
 * 카드 이동수단 막대 presentation:
 * - 앞뒤가 모두 대중교통인 walk 0분 → 환승으로 표시
 * - 그 외 walk 0분(시작/끝 등) → 숨김
 */
function toPresentationTransitSteps(steps: V2TransitStep[]): V2TransitStep[] {
  const presented: V2TransitStep[] = [];

  for (let index = 0; index < steps.length; index += 1) {
    const step = steps[index];
    if (!(step.mode === 'walk' && step.durationMin === 0)) {
      presented.push(step);
      continue;
    }

    const prev = steps[index - 1];
    const next = steps[index + 1];
    const betweenTransit =
      prev != null &&
      next != null &&
      isTransitBarMode(prev.mode) &&
      isTransitBarMode(next.mode);

    if (betweenTransit) {
      presented.push({
        ...step,
        mode: 'transfer',
        modeLabel: '환승',
        durationMin: 0,
        routeLabel: undefined,
        subwayLineId: undefined,
      });
    }
  }

  return presented;
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
  // transfer 및 기타 수단: 기존 환승 화살표 아이콘
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 8h12l-3-3M19 16H7l3 3" />
    </svg>
  );
}

function TransitSequence({ steps }: { steps: V2TransitStep[] }) {
  const visibleSteps = toPresentationTransitSteps(steps);
  if (visibleSteps.length === 0) return null;
  const compact = visibleSteps.length >= 5;

  return (
    <ol
      className="map-first__route-card-transit"
      aria-label="이동 수단 순서"
      data-compact={compact ? 'true' : undefined}
    >
      {visibleSteps.map((step) => (
        <li
          key={step.id}
          data-mode={step.mode}
          data-subway-line={step.subwayLineId}
          aria-label={transitAccessibleLabel(step)}
          style={{
            flexGrow: segmentFlexGrow(step, compact),
            flexShrink: 1,
            flexBasis: 0,
          }}
        >
          <span className="map-first__transit-icon" aria-hidden="true">
            <TransitModeIcon mode={step.mode} />
          </span>
          <span className="map-first__transit-copy">
            {step.mode === 'transfer' ? '환승' : `${step.durationMin}분`}
          </span>
        </li>
      ))}
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
  const cardTitle = formatRouteTransitTitle(view.transitSteps, view.summary);

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
      aria-label={`${view.rank}순위 경로, ${cardTitle}, 소요 ${durationLabel}, ${reasonHighlights.join(', ')}, ${view.score.ariaLabel}`}
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
          <h3 className="map-first__route-card-summary">{cardTitle}</h3>
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
