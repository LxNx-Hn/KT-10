import { useAppStore } from '@/store/appStore';
import { WEATHER_SCENARIOS, type WeatherScenarioId } from '@/data/weather';
import type { AirQuality, WeatherCondition } from '@/types';

const SCENARIO_ICON: Record<WeatherScenarioId, string> = {
  normal: '☀️',
  heatwave: '🥵',
  coldwave: '🥶',
  rain: '🌧️',
  dust: '😷',
};

const AIR_LABEL: Record<AirQuality, string> = {
  good: '좋음',
  moderate: '보통',
  bad: '나쁨',
  very_bad: '매우 나쁨',
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

/** 원 데이터 필드에 있는 주의 신호만 사용한다. 체감온도 임계값은 새로 만들지 않는다. */
function resolveWeatherCaution(weather: WeatherCondition): string[] {
  const notes: string[] = [];
  if (weather.isHeatwave) notes.push('폭염 관련 정보가 있어요');
  if (weather.isColdwave) notes.push('한파 관련 정보가 있어요');
  if (weather.precipitationMm > 0 || weather.sky === 'rain' || weather.sky === 'snow') {
    notes.push(`강수 ${weather.precipitationMm}mm`);
  }
  if (weather.air === 'bad' || weather.air === 'very_bad') {
    notes.push(`대기질 ${AIR_LABEL[weather.air]}`);
  }
  return notes;
}

/**
 * 실시간 날씨와 경로 노출 특성을 안내한다. 내부 위험 점수는 노출하지 않는다.
 */
export default function WeatherWarning() {
  const weather = useAppStore((s) => s.weather);
  const weatherScenario = useAppStore((s) => s.weatherScenario);
  const setWeatherScenario = useAppStore((s) => s.setWeatherScenario);
  const live = import.meta.env.VITE_DATA_SOURCE !== 'mock';
  const cautionNotes = weather ? resolveWeatherCaution(weather) : [];
  const hasWeatherCaution = cautionNotes.length > 0;

  return (
    <section className="weather" aria-label="날씨 안내">
      <h2 className="section-title">날씨 안내</h2>

      {weather && (
        <div
          className={`weather__banner weather__banner--${hasWeatherCaution ? 'warn' : 'neutral'}`}
          role="status"
        >
          <strong>
            {hasWeatherCaution
              ? '현재 확인된 날씨·대기질에 유의하세요.'
              : '현재 날씨 정보를 확인하고 이동하세요.'}
          </strong>
          {hasWeatherCaution && (
            <span> · {cautionNotes.join(' · ')}</span>
          )}
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
          <span>
            미세먼지 PM10 {weather.pm10}
            {Number.isFinite(weather.pm10) ? '㎍/m³' : ''}
            {weather.air ? ` · ${AIR_LABEL[weather.air]}` : ''}
          </span>
        </div>
      )}
    </section>
  );
}
