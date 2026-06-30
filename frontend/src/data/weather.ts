import type { WeatherCondition } from '@/types';
import weatherJson from '@data/weather.json';

/**
 * 날씨 시나리오 — 공유 데이터셋(data/weather.json). 검증(기획서 §8)과 데모 토글에 사용.
 */
export type WeatherScenarioId = 'normal' | 'heatwave' | 'coldwave' | 'rain' | 'dust';

export const WEATHER_SCENARIOS = weatherJson as unknown as Record<
  WeatherScenarioId,
  WeatherCondition
>;

export const DEFAULT_WEATHER: WeatherScenarioId = 'normal';
