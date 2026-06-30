import type { ScoredRoute } from '@/types';
import { useAppStore } from '@/store/appStore';
import { speak } from '@/voice/synthesis';
import {
  ScoreBar,
  elevatorBadge,
  lowFloorBadge,
  weatherRiskBadge,
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
  const selected = selectedRouteId === route.id;

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
        <div className="route-card__final" title="최종 추천 점수">
          <span className="route-card__final-num">{Math.round(score.finalScore)}</span>
          <span className="route-card__final-unit">점</span>
        </div>
      </header>

      <ul className="route-card__stats">
        <li><b>{route.totalDurationMin}</b>분</li>
        <li>도보 <b>{route.totalWalkM}</b>m</li>
        <li>환승 <b>{route.transferCount}</b>회</li>
      </ul>

      <div className="route-card__badges">
        {lowFloorBadge(score.lowFloorStatus)}
        {elevatorBadge(score.components.elevator)}
        {weatherRiskBadge(score.display.weatherRisk)}
      </div>

      <ScoreBar label="접근성 점수" value={score.components.accessibility} />

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
