import type { WeatherCondition } from '@/types';

/**
 * 날씨 시나리오 mock. 검증(기획서 §8)과 데모 토글에 사용한다.
 * 키를 바꾸면 동일 경로의 날씨 점수가 달라지는지 확인할 수 있다.
 */
export type WeatherScenarioId = 'normal' | 'heatwave' | 'coldwave' | 'rain' | 'dust';

export const WEATHER_SCENARIOS: Record<WeatherScenarioId, WeatherCondition> = {
  normal: {
    label: '평상 (맑음)',
    tempC: 21,
    feelsLikeC: 21,
    precipitationMm: 0,
    isHeatwave: false,
    isColdwave: false,
    windMs: 2,
    pm10: 30,
    sky: 'clear',
    air: 'good',
  },
  heatwave: {
    label: '폭염',
    tempC: 36,
    feelsLikeC: 39,
    precipitationMm: 0,
    isHeatwave: true,
    isColdwave: false,
    windMs: 1,
    pm10: 55,
    sky: 'clear',
    air: 'moderate',
  },
  coldwave: {
    label: '한파',
    tempC: -8,
    feelsLikeC: -14,
    precipitationMm: 0,
    isHeatwave: false,
    isColdwave: true,
    windMs: 7,
    pm10: 40,
    sky: 'cloudy',
    air: 'moderate',
  },
  rain: {
    label: '비',
    tempC: 18,
    feelsLikeC: 18,
    precipitationMm: 7,
    isHeatwave: false,
    isColdwave: false,
    windMs: 5,
    pm10: 20,
    sky: 'rain',
    air: 'good',
  },
  dust: {
    label: '미세먼지 나쁨',
    tempC: 14,
    feelsLikeC: 14,
    precipitationMm: 0,
    isHeatwave: false,
    isColdwave: false,
    windMs: 3,
    pm10: 145,
    sky: 'cloudy',
    air: 'very_bad',
  },
};

export const DEFAULT_WEATHER: WeatherScenarioId = 'normal';
