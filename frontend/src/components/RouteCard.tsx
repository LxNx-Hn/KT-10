import type { ScoredRoute } from '@/types';
import { useAppStore } from '@/store/appStore';
import { speak } from '@/voice/synthesis';
import {
  Badge,
  lowFloorBadge,
} from './ui';

export default function RouteCard({
  item,
  rank,
}: {
  item: ScoredRoute;
  rank: number;
}) {
  const { route, score } = item;
  const selectedRouteId = useAppStore((s) => s.selectedRouteId);
  const selectRoute = useAppStore((s) => s.selectRoute);
  const setLastSpoken = useAppStore((s) => s.setLastSpoken);
  const recommendations = useAppStore((s) => s.recommendations);
  const selected = selectedRouteId === route.id;

  const minimumDuration = Math.min(...recommendations.map((r) => r.route.totalDurationMin));
  const minimumTransfers = Math.min(...recommendations.map((r) => r.route.transferCount));
  const minimumWalk = Math.min(...recommendations.map((r) => r.route.totalWalkM));
  const characteristic = route.totalDurationMin === minimumDuration
    ? '이동시간이 가장 짧은 경로'
    : route.transferCount === minimumTransfers
      ? '환승이 가장 적은 경로'
      : route.totalWalkM === minimumWalk
        ? '도보 이동이 가장 짧은 경로'
        : '접근성 특성을 고려한 경로';

  const stairSegments = route.segments.filter((segment) => segment.mode === 'walk' || segment.mode === 'transfer');
  const stairKnown = stairSegments.some((segment) => segment.hasStairs !== undefined);
  const hasStairs = stairSegments.some((segment) => segment.hasStairs === true);
  const stairCount = stairSegments.reduce((sum, segment) => sum + (segment.stairsCount ?? 0), 0);
  const verticalSegments = route.segments.filter((segment) => segment.needsVerticalMove);
  const hasElevator = verticalSegments.some((segment) => segment.hasElevator === true);
  const elevatorUnavailable = verticalSegments.length > 0
    && verticalSegments.every((segment) => segment.hasElevator === false);
  const hasSlope = route.segments.some((segment) => segment.hasSlope === true);
  const terrain = route.terrain;

  const speakRoute = () => {
    const text = `${score.voiceSummary} 추천 이유, ${score.reasons.join(' ')} ${
      score.cautions.length ? '주의사항, ' + score.cautions.join(' ') : ''
    }`;
    setLastSpoken(text);
    speak(text);
  };

  return (
    <article
      className={`route-card ${selected ? 'route-card--selected' : ''}`}
      aria-label={`${rank}번 추천 경로`}
      onClick={() => selectRoute(route.id)}
    >
      <header className="route-card__head">
        <div className="route-card__rank">{rank}</div>
        <div className="route-card__title">
          <h3>{route.summary}</h3>
          <p className="route-card__od">
            {route.origin} → {route.destination}
          </p>
        </div>
        <div className="route-card__feature" aria-label="경로 대표 특성">
          {characteristic}
        </div>
      </header>

      <ul className="route-card__stats">
        <li><b>{route.totalDurationMin}</b>분</li>
        <li>도보 <b>{route.totalWalkM}</b>m</li>
        <li>환승 <b>{route.transferCount}</b>회</li>
      </ul>

      <div className="route-card__badges">
        {lowFloorBadge(score.lowFloorStatus)}
        {verticalSegments.length === 0
          ? <Badge tone="neutral">수직이동 없음</Badge>
          : hasElevator
            ? <Badge tone="good">승강기 이용 확인</Badge>
            : elevatorUnavailable
              ? <Badge tone="bad">승강기 이용 불가 확인</Badge>
              : <Badge tone="warn">승강기 정보 미확인</Badge>}
        {hasStairs
          ? <Badge tone="bad">계단 {stairCount ? `${stairCount}개` : '포함'}</Badge>
          : stairKnown
            ? <Badge tone="good">계단 없음 확인</Badge>
            : <Badge tone="warn">계단 정보 미확인</Badge>}
        {hasSlope && <Badge tone="warn">경사 구간 포함</Badge>}
        {terrain?.status === 'estimated_90m' && terrain.avgSlopePercent !== undefined && (
          <Badge tone="neutral">평균 경사 {terrain.avgSlopePercent.toFixed(1)}% · 90m 지형 추정</Badge>
        )}
        {terrain?.status === 'estimated_90m' && terrain.elevationGainM !== undefined && terrain.elevationGainM > 0 && (
          <Badge tone="neutral">누적 오르막 {Math.round(terrain.elevationGainM)}m</Badge>
        )}
      </div>

      {score.reasons.length > 0 && (
        <div className="route-card__reasons">
          <h4>추천 이유</h4>
          <ul>
            {score.reasons.map((r, i) => (
              <li key={i}>✓ {r}</li>
            ))}
          </ul>
        </div>
      )}

      {score.cautions.length > 0 && (
        <div className="route-card__cautions">
          <h4>주의사항</h4>
          <ul>
            {score.cautions.map((c, i) => (
              <li key={i}>⚠ {c}</li>
            ))}
          </ul>
        </div>
      )}

      <button
        type="button"
        className="btn btn--listen"
        onClick={(e) => {
          e.stopPropagation();
          speakRoute();
        }}
      >
        🔊 이 경로 음성으로 듣기
      </button>
    </article>
  );
}
