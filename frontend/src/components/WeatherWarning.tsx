import { useAppStore } from '@/store/appStore';
import { WEATHER_SCENARIOS, type WeatherScenarioId } from '@/data/weather';
import type { WeatherCondition } from '@/types';

const SCENARIO_ICON: Record<WeatherScenarioId, string> = {
  normal: '☀️',
  heatwave: '🥵',
  coldwave: '🥶',
  rain: '🌧️',
  dust: '😷',
};

function iconForWeather(weather: WeatherCondition): string {
  if (weather.sky === 'snow') return '🌨️';
  if (weather.sky === 'rain' || weather.precipitationMm > 0) return '🌧️';
  if (weather.air === 'bad' || weather.air === 'very_bad') return '😷';
  if (weather.isHeatwave) return '🥵';
  if (weather.isColdwave) return '🥶';
  if (weather.sky === 'cloudy') return '☁️';
  return '☀️';
}

/**
 * 실시간 날씨와 경로 노출 특성을 안내한다. 내부 위험 점수는 노출하지 않는다.
 */
export default function WeatherWarning() {
  const weather = useAppStore((s) => s.weather);
  const weatherScenario = useAppStore((s) => s.weatherScenario);
  const setWeatherScenario = useAppStore((s) => s.setWeatherScenario);
  const live = import.meta.env.VITE_DATA_SOURCE === 'live';
  const hasWeatherCaution = Boolean(
    weather && (weather.precipitationMm > 0 || weather.air === 'bad' || weather.air === 'very_bad'),
  );

  return (
    <section className="weather" aria-label="날씨 안내">
      <h2 className="section-title">날씨 안내</h2>

      {weather && (
        <div className={`weather__banner weather__banner--${hasWeatherCaution ? 'warn' : 'good'}`} role="status">
          <strong>
            {hasWeatherCaution
              ? '경로 계산에 사용된 기상·대기 값을 확인하세요.'
              : '경로 계산에 사용된 값에는 강수·나쁜 대기질이 없습니다.'}
          </strong>
          {weather.precipitationMm > 0 && <span> · 강수 {weather.precipitationMm}mm</span>}
          {(weather.air === 'bad' || weather.air === 'very_bad') && <span> · 대기질 {weather.air}</span>}
        </div>
      )}

      {!live && <div className="weather__scenarios" role="group" aria-label="날씨 시나리오(데모)">
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
      </div>}

      {weather && (
        <div className="weather__now">
          <span>{iconForWeather(weather)} 체감 {weather.feelsLikeC}℃</span>
          <span>강수 {weather.precipitationMm}mm</span>
          <span>풍속 {weather.windMs}m/s</span>
          <span>미세먼지 PM10 {weather.pm10}</span>
        </div>
      )}
    </section>
  );
}
