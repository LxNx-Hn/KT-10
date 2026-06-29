import { useAppStore } from '@/store/appStore';
import { WEATHER_SCENARIOS, type WeatherScenarioId } from '@/data/weather';

const SCENARIO_ICON: Record<WeatherScenarioId, string> = {
  normal: '☀️',
  heatwave: '🥵',
  coldwave: '🥶',
  rain: '🌧️',
  dust: '😷',
};

/**
 * 날씨 경고 + 점수 반영 컨트롤(요구사항 §3 RouteResultSection).
 * 추천 1순위(또는 선택 경로)의 날씨 위험을 텍스트로 경고하고, 데모 시나리오를 토글한다.
 */
export default function WeatherWarning() {
  const weather = useAppStore((s) => s.weather);
  const weatherScenario = useAppStore((s) => s.weatherScenario);
  const setWeatherScenario = useAppStore((s) => s.setWeatherScenario);
  const weatherAvoid = useAppStore((s) => s.options.weatherAvoid);
  const toggleWeatherAvoid = useAppStore((s) => s.toggleWeatherAvoid);
  const recommendations = useAppStore((s) => s.recommendations);
  const selectedRouteId = useAppStore((s) => s.selectedRouteId);

  const target =
    recommendations.find((r) => r.route.id === selectedRouteId) ?? recommendations[0];
  const risk = target?.score.display.weatherRisk ?? 0;
  const level = risk >= 40 ? 'bad' : risk >= 20 ? 'warn' : 'good';
  const levelText = risk >= 40 ? '높음' : risk >= 20 ? '보통' : '낮음';

  return (
    <section className="weather" aria-label="날씨 안내">
      <h2 className="section-title">날씨 안내 · 점수 반영</h2>

      {target && (
        <div className={`weather__banner weather__banner--${level}`} role="status">
          <strong>현재 경로 날씨 위험: {levelText} ({Math.round(risk)}/100)</strong>
          {target.score.cautions
            .filter((c) => /폭염|한파|비|미세먼지|미끄/.test(c))
            .map((c, i) => (
              <span key={i}> · {c}</span>
            ))}
        </div>
      )}

      <div className="weather__scenarios" role="group" aria-label="날씨 시나리오(데모)">
        {(Object.keys(WEATHER_SCENARIOS) as WeatherScenarioId[]).map((id) => (
          <button
            key={id}
            type="button"
            className={`chip ${weatherScenario === id ? 'chip--active' : ''}`}
            onClick={() => void setWeatherScenario(id)}
          >
            {SCENARIO_ICON[id]} {WEATHER_SCENARIOS[id].label}
          </button>
        ))}
      </div>

      {weather && (
        <div className="weather__now">
          <span>{SCENARIO_ICON[weatherScenario]} 체감 {weather.feelsLikeC}℃</span>
          <span>강수 {weather.precipitationMm}mm</span>
          <span>풍속 {weather.windMs}m/s</span>
          <span>미세먼지 PM10 {weather.pm10}</span>
        </div>
      )}

      <label className="weather__avoid">
        <input type="checkbox" checked={!!weatherAvoid} onChange={toggleWeatherAvoid} />
        날씨 위험 회피 우선 (점수 가중 강화)
      </label>
    </section>
  );
}
