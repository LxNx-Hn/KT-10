// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import WeatherWarning from '@/components/WeatherWarning';
import { useAppStore } from '@/store/appStore';
import type { WeatherCondition } from '@/types';

afterEach(() => {
  cleanup();
});

function setWeather(weather: WeatherCondition) {
  useAppStore.setState({ weather, weatherScenario: 'normal' });
}

describe('날씨 안내 문구', () => {
  it('위험도 필드가 없으면 양호를 단정하지 않는다', () => {
    setWeather({
      label: '더운 날',
      tempC: 33,
      feelsLikeC: 34.2,
      precipitationMm: 0,
      windMs: 2,
      pm10: 40,
      sky: 'clear',
      air: 'moderate',
    });

    render(<WeatherWarning />);
    expect(screen.getByRole('status').textContent).toContain(
      '현재 날씨 정보를 확인하고 이동하세요.',
    );
    expect(screen.getByRole('status').textContent).not.toContain('양호');
    expect(screen.getByRole('status').textContent).not.toContain('경로 구간');
    expect(screen.getByText(/미세먼지 PM10 40㎍\/m³ · 보통/)).toBeTruthy();
  });

  it('공식 폭염 플래그가 있으면 주의 안내를 표시한다', () => {
    setWeather({
      label: '폭염',
      tempC: 36,
      feelsLikeC: 39,
      precipitationMm: 0,
      isHeatwave: true,
      windMs: 1,
      pm10: 55,
      sky: 'clear',
      air: 'moderate',
    });

    render(<WeatherWarning />);
    expect(screen.getByRole('status').textContent).toContain(
      '현재 확인된 날씨·대기질에 유의하세요.',
    );
    expect(screen.getByRole('status').textContent).toContain('폭염');
    expect(screen.getByRole('status').textContent).not.toContain('양호');
  });
});
