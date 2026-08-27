import type { RouteCandidate, RouteScore, ScoredRoute } from '@/types';
import { useAppStore } from '@/store/appStore';
import { formatDurationMin } from '@/utils/formatDurationMin';
import { formatDistanceM } from '@/utils/formatDistanceM';
import { speak } from '@/voice/synthesis';
import { Badge, lowFloorBadge } from './ui';

const CHARACTERISTIC_LABEL: Record<
  NonNullable<RouteCandidate['characteristics']>[number],
  string
> = {
  fastest: '제일 빠른 길',
  shortest_walk: '도보가 가장 짧은 길',
  lowest_slope: '경사가 가장 완만한 길',
  most_shade: '건물 그늘이 가장 많은 길',
  fewest_transfers: '환승이 가장 적은 길',
  stair_free: '계단 없음',
  low_floor_confirmed: '저상버스 이용 가능',
};

const SCORE_KIND_LABEL: Record<NonNullable<RouteScore['scoreKind']>, string> = {
  rule_baseline: '프로필 적합 점수',
  bootstrap_baseline: '프로필 적합 점수',
  human_model: '프로필 적합 점수',
};

export default function RouteCard({
  item,
  rank,
}: {
  item: ScoredRoute;
  rank: number;
}) {
  const { route, score } = item;
  const selectedRouteId = useAppStore((state) => state.selectedRouteId);
  const selectRoute = useAppStore((state) => state.selectRoute);
  const setLastSpoken = useAppStore((state) => state.setLastSpoken);
  const selected = selectedRouteId === route.id;
  const scoreLabel = SCORE_KIND_LABEL[score.scoreKind ?? 'rule_baseline'];
  const characteristicLabels = (route.characteristics ?? []).map(
    (characteristic) => CHARACTERISTIC_LABEL[characteristic],
  );
  const evidencedTraitLabels = (route.traitLabels ?? [])
    .filter((trait) => trait.evidenceStatus !== 'unavailable')
    .map((trait) => trait.displayLabel);
  const visibleTraitLabels = Array.from(
    new Set([...characteristicLabels, ...evidencedTraitLabels]),
  );
  const unavailableTraits = (route.traitLabels ?? []).filter(
    (trait) => trait.evidenceStatus === 'unavailable',
  );

  const stairSegments = route.segments.filter(
    (segment) => segment.mode === 'walk' || segment.mode === 'transfer',
  );
  const hasStairs = stairSegments.some(
    (segment) => segment.hasStairs === true || (segment.stairsCount ?? 0) > 0,
  );
  const stairFreeConfirmed = stairSegments.length > 0
    && stairSegments.every(
      (segment) => segment.hasStairs === false || segment.stairsCount === 0,
    );
  const stairCount = stairSegments.reduce(
    (sum, segment) => sum + (segment.stairsCount ?? 0),
    0,
  );
  const verticalSegments = route.segments.filter(
    (segment) => segment.needsVerticalMove === true,
  );
  const noVerticalMoveConfirmed = route.segments.length > 0
    && route.segments.every((segment) => segment.needsVerticalMove === false);
  const hasElevator = verticalSegments.some((segment) => segment.hasElevator === true);
  const hasSlope = route.segments.some((segment) => segment.hasSlope === true);
  const terrain = route.terrain;
  const knownShade = (
    route.shade?.status === 'estimated_demo'
    || route.shade?.status === 'estimated_public'
  ) && route.shade.shadeRatio !== undefined;

  const speakRoute = () => {
    const text = `${score.voiceSummary} 추천 이유, ${score.reasons.join(' ')} ${
      score.cautions.length ? `주의사항, ${score.cautions.join(' ')}` : ''
    }`;
    setLastSpoken(text);
    speak(text);
  };

  return (
    <article
      className={`route-card ${selected ? 'route-card--selected' : ''}`}
      role="listitem"
      data-route-id={route.id}
      aria-label={`${rank}순위 경로, ${scoreLabel} ${Math.round(score.finalScore)}점`}
      aria-current={selected ? 'true' : undefined}
      tabIndex={0}
      onClick={() => selectRoute(route.id)}
      onKeyDown={(event) => {
        // Tab focus 이동만으로 외부 대중교통 정밀화를 시작하지 않는다.
        // 비버튼 카드의 키보드 선택은 Enter·Space에서만 명시적으로 처리한다.
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          selectRoute(route.id);
        }
      }}
    >
      <header className="route-card__head">
        <div className="route-card__rank"><strong>{rank}</strong>순위</div>
        <div className="route-card__title">
          <h3>{route.summary}</h3>
          <p className="route-card__od">
            {route.origin} → {route.destination}
          </p>
        </div>
        <div className="route-card__score">
          <span>{scoreLabel}</span>
          <strong>{Math.round(score.finalScore)}</strong><small>/100</small>
        </div>
      </header>

      {visibleTraitLabels.length > 0 && (
        <div className="route-card__traits" aria-label="경로 사실 특성">
          {visibleTraitLabels.slice(0, 3).map((label) => (
            <span key={label}>{label}</span>
          ))}
          {visibleTraitLabels.length > 3 && (
            <span>특성 +{visibleTraitLabels.length - 3}</span>
          )}
        </div>
      )}

      <ul className="route-card__stats" aria-label="경로 요약">
        <li><b>{formatDurationMin(route.totalDurationMin)}</b></li>
        <li><b>{formatDistanceM(route.totalWalkM)}</b><span>m 도보</span></li>
        <li><b>{route.transferCount}</b><span>회 환승</span></li>
        {knownShade && (
          <li><b>{Math.round(route.shade!.shadeRatio! * 100)}</b><span>% 건물 그늘</span></li>
        )}
      </ul>

      <div className="route-card__quick-facts">
        {terrain?.status === 'estimated_90m' && terrain.avgSlopePercent !== undefined && (
          <Badge tone="neutral">보행구간 평균 경사 {terrain.avgSlopePercent.toFixed(1)}%</Badge>
        )}
        {hasStairs
          ? <Badge tone="bad">계단 {stairCount ? `${stairCount}개` : '포함'}</Badge>
          : stairFreeConfirmed
            ? <Badge tone="good">계단 없음</Badge>
            : null}
        {route.transferCount === 0 && <Badge tone="good">환승 없음</Badge>}
      </div>

      <details className="route-card__details">
        <summary>추천 근거와 접근성 정보</summary>

        <div className="route-card__badges">
          {lowFloorBadge(score.lowFloorStatus)}
          {noVerticalMoveConfirmed
            ? <Badge tone="neutral">수직이동 없음</Badge>
            : hasElevator
              ? <Badge tone="good">승강기 이용 가능</Badge>
              : null}
          {hasSlope && <Badge tone="warn">경사 구간</Badge>}
          {terrain?.status === 'estimated_90m' && terrain.avgSlopePercent !== undefined && (
            <Badge tone="neutral">
              보행구간 평균 경사 {terrain.avgSlopePercent.toFixed(1)}%
            </Badge>
          )}
          {terrain?.status === 'estimated_90m'
            && terrain.elevationGainM !== undefined
            && terrain.elevationGainM > 0 && (
            <Badge tone="neutral">누적 오르막 {Math.round(terrain.elevationGainM)}m</Badge>
          )}
          {knownShade && (
            <Badge tone="good">
              {route.shade!.estimateKind === 'lower_bound'
                ? '확인된 건물 그늘 최소 '
                : '건물 그늘 '}
              {Math.round(route.shade!.shadeRatio! * 100)}%
            </Badge>
          )}
          {route.shade?.status === 'estimated_demo' && (
            <Badge tone="neutral">데모 건물 높이</Badge>
          )}
          {route.shade?.status === 'estimated_public' && (
            <Badge tone="neutral">
              공공 건물 높이 {route.shade.knownHeightBuildingCount ?? 0}
              /{route.shade.buildingCount ?? 0}건
            </Badge>
          )}
          {(route.shade?.status === 'estimated_demo'
            || route.shade?.status === 'estimated_public') && (
            <Badge tone="neutral">건물 그늘 기준</Badge>
          )}
          {/* Unconfirmed / Unavailable shade badges omitted per UI confirmed-only rule */}
        </div>



        {score.reasons.length > 0 && (
          <div className="route-card__reasons">
            <h4>추천 이유</h4>
            <ul>
              {score.reasons.map((reason) => <li key={reason}>✓ {reason}</li>)}
            </ul>
          </div>
        )}

        {score.cautions.length > 0 && (
          <div className="route-card__cautions">
            <h4>주의사항</h4>
            <ul>
              {score.cautions.map((caution) => <li key={caution}>⚠ {caution}</li>)}
            </ul>
          </div>
        )}

        {unavailableTraits.length > 0 && (
          <div className="route-card__unavailable">
            <h4>확인되지 않은 특성</h4>
            <ul>
              {unavailableTraits.map((trait) => (
                <li key={trait.labelId}>{trait.displayLabel}</li>
              ))}
            </ul>
          </div>
        )}
      </details>

      <button
        type="button"
        className="btn btn--listen"
        onClick={(event) => {
          event.stopPropagation();
          speakRoute();
        }}
      >
        🔊 이 경로 듣기
      </button>
    </article>
  );
}
