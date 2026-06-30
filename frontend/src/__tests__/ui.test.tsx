// @vitest-environment jsdom
/**
 * UI 상태 테스트 (요구사항 §12).
 * - 첫 화면에서 지도보다 검색창이 먼저 렌더링되는가
 * - 프로필 칩 4개가 보이는가
 * - 음성 챗봇이 하단(문서 마지막)에 고정 영역으로 존재하는가
 * - 경로 검색 후 RouteCards 가 MapView 보다 먼저 표시되는가
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { act, cleanup, render } from '@testing-library/react';
import App from '@/App';
import { useAppStore } from '@/store/appStore';
import { recommendRoutes } from '@/scoring/engine';
import { demoCandidates } from '@/data/routes';
import { WEATHER_SCENARIOS } from '@/data/weather';
import { findPlace } from '@/data/places';

/** a 가 문서상 b 보다 앞에 있으면 true */
function precedes(a: Element, b: Element): boolean {
  return Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
}

function seedResults() {
  const candidates = demoCandidates();
  const weather = WEATHER_SCENARIOS.normal;
  const recommendations = recommendRoutes(candidates, weather, 'general');
  useAppStore.setState({
    origin: findPlace('gu-office') ?? null,
    destination: findPlace('seomyeon-stn') ?? null,
    candidates,
    weather,
    recommendations,
    selectedRouteId: recommendations[0]?.route.id ?? null,
  });
}

beforeEach(() => {
  useAppStore.setState({
    origin: null,
    destination: null,
    candidates: [],
    recommendations: [],
    selectedRouteId: null,
    loading: false,
    error: null,
  });
});
afterEach(() => cleanup());

describe('UI 상태 — 검색 중심 구조', () => {
  it('첫 화면에서 검색창이 지도 섹션보다 먼저 렌더링된다', () => {
    const { container } = render(<App />);
    const searchInput = container.querySelector('.place-input__field');
    const mapSection = container.querySelector('.mappreview');
    expect(searchInput).toBeTruthy();
    expect(mapSection).toBeTruthy();
    expect(precedes(searchInput!, mapSection!)).toBe(true);
  });

  it('프로필 칩 4개가 보인다', () => {
    const { container } = render(<App />);
    expect(container.querySelectorAll('[role="radio"]').length).toBe(4);
  });

  it('첫 화면에는 지도(MapView)가 펼쳐져 있지 않다', () => {
    const { container } = render(<App />);
    expect(container.querySelector('.map')).toBeNull();
  });

  it('음성 챗봇 Dock 이 문서 마지막(하단 고정 영역)에 존재한다', () => {
    const { container } = render(<App />);
    const dock = container.querySelector('.voicedock');
    const main = container.querySelector('.app__main');
    expect(dock).toBeTruthy();
    expect(dock!.getAttribute('aria-label')).toBe('음성 챗봇');
    expect(precedes(main!, dock!)).toBe(true);
    // 마이크/말하기 버튼 포함
    expect(dock!.querySelector('.voice-fab')).toBeTruthy();
  });

  it('경로 검색 후 RouteCards 가 MapView 보다 먼저 표시된다', () => {
    const { container } = render(<App />);
    act(() => seedResults());
    const routeCard = container.querySelector('.route-card');
    const map = container.querySelector('.map');
    expect(routeCard).toBeTruthy();
    expect(map).toBeTruthy(); // 결과가 생기면 지도 자동 확장
    expect(precedes(routeCard!, map!)).toBe(true);
  });
});
