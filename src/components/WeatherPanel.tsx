import { useAppStore } from '@/store/appStore';
import { WEATHER_SCENARIOS, type WeatherScenarioId } from '@/data/weather';

const SCENARIO_ICON: Record<WeatherScenarioId, string> = {
  normal: '☀️',
  heatwave: '🥵',
  coldwave: '🥶',
  rain: '🌧️',
  dust: '😷',
};

export default function WeatherPanel() {
  const weather = useAppStore((s) => s.weather);
  const weatherScenario = useAppStore((s) => s.weatherScenario);
  const setWeatherScenario = useAppStore((s) => s.setWeatherScenario);
  const weatherAvoid = useAppStore((s) => s.options.weatherAvoid);
  const toggleWeatherAvoid = useAppStore((s) => s.toggleWeatherAvoid);

  return (
    <section className="weather" aria-label="날씨 안내">
      <h2 className="section-title">날씨 · 점수 반영</h2>

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
