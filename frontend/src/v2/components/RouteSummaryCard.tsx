import {
  type V2RouteFactKind,
  type V2RouteViewModel,
} from '../routeViewModel';

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
  const prioritizedFacts = [...view.facts].sort((left, right) => {
    const priority = (id: string) => {
      if (id === 'shade') return 0;
      if (id === 'terrain' || id === 'elevation-gain') return 1;
      if (id === 'stairs') return 2;
      if (id === 'elevator') return 3;
      return 4;
    };
    return priority(left.id) - priority(right.id);
  });
  const badgeCandidates: Array<{
    label: string;
    kind: V2RouteFactKind;
  }> = [
    ...prioritizedFacts.map((fact) => ({
      label: fact.label,
      kind: fact.kind,
    })),
    ...view.characteristicLabels.map((label) => ({
      label,
      kind: 'advantage' as const,
    })),
    ...view.traitLabels.map((label) => ({
      label,
      kind: 'advantage' as const,
    })),
  ];
  const badges = badgeCandidates.filter(
    (badge, index, all) =>
      all.findIndex((candidate) => candidate.label === badge.label) === index,
  );
  const shadeFact = view.facts.find((fact) => fact.id === 'shade');
  const shadeReason =
    shadeFact && (shadeFact.kind === 'unknown' || shadeFact.kind === 'neutral')
      ? shadeFact.detail
      : undefined;

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
      aria-label={`${view.rank}순위 경로, ${view.scoreKindLabel} ${view.score.rounded}점`}
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
      <header className="map-first__route-card-head">
        <span className="map-first__rank-badge">{view.rank}순위</span>
        <div className="map-first__route-card-title">
          <h3>{view.summary}</h3>
          <p>{view.title}</p>
        </div>
        <div className="map-first__route-score">
          <strong>{view.score.rounded}</strong>
          <span>/100</span>
          <small>{view.scoreKindLabel}</small>
        </div>
      </header>

      <ul className="map-first__route-stats" aria-label="경로 요약">
        <li>
          <strong>{view.stats.durationMin}</strong>
          <span>분</span>
        </li>
        <li>
          <strong>{view.stats.walkM}</strong>
          <span>m 도보</span>
        </li>
        <li>
          <strong>{view.stats.transferCount}</strong>
          <span>회 환승</span>
        </li>
      </ul>

      <div className="map-first__badges" aria-label="경로 사실 특성">
        {badges.slice(0, 4).map((badge) => (
          <span
            key={badge.label}
            className={`map-first__badge map-first__badge--${badge.kind}`}
          >
            {badge.label}
          </span>
        ))}
        {badges.length > 4 && (
          <span className="map-first__badge">특성 +{badges.length - 4}</span>
        )}
      </div>

      {shadeReason && (
        <p className="map-first__shade-reason">{shadeReason}</p>
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
