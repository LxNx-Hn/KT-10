// @vitest-environment jsdom
/**
 * UI 상태 테스트 (요구사항 §12).
 * - 첫 화면에서 지도보다 검색창이 먼저 렌더링되는가
 * - 프로필 칩 4개가 보이는가
 * - 음성 챗봇이 하단(문서 마지막)에 고정 영역으로 존재하는가
 * - 경로 검색 후 RouteCards 가 MapView 보다 먼저 표시되는가
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render } from '@testing-library/react';
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

function seedShadedResults() {
  seedResults();
  const state = useAppStore.getState();
  const recommendations = state.recommendations.map((item, index) => {
    if (index !== 0) return item;
    const path = item.route.path ?? [];
    const start = path[0] ?? { lat: 35.1629, lng: 129.0532 };
    const end = path[1] ?? { lat: 35.1628, lng: 129.0533 };
    return {
      ...item,
      route: {
        ...item.route,
        shade: {
          status: 'estimated_demo' as const,
          evaluatedAt: '2026-07-23T14:00:00+09:00',
          shadeRatio: 0.5,
          includesTreeShade: false,
          includesTerrainShadow: false,
          source: '합성 건물',
          dataQuality: 'demo' as const,
          shadowPolygons: [[
            start,
            { lat: start.lat, lng: end.lng },
            end,
            { lat: end.lat, lng: start.lng },
            start,
          ]],
          pathSegments: [
            { start, end, shaded: true },
            { start: end, end: path[2] ?? end, shaded: false },
          ],
          calculationNote: '테스트',
        },
      },
    };
  });
  useAppStore.setState({ recommendations });
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
afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

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
    // 기본은 콘텐츠를 가리지 않도록 접혀 있고, 펼치면 마이크 버튼이 나타난다.
    const handle = dock!.querySelector('.voicedock__handle');
    expect(handle?.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(handle!);
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

  it('경로 카드에는 내부 점수를 노출하지 않고 대표 특성을 표시한다', () => {
    const { container } = render(<App />);
    act(() => seedResults());
    expect(container.querySelector('.route-card__final')).toBeNull();
    expect(container.querySelector('.route-card__feature')?.textContent).toMatch(/경로|이동시간|환승|도보/);
    expect(container.querySelector('.scoreval')).toBeNull();
  });

  it('건물 그림자는 경로 아래에 그리고 그늘·햇빛 구간 색을 구분한다', () => {
    vi.stubEnv('VITE_KAKAO_MAP_KEY', '');
    const { container } = render(<App />);
    act(() => seedShadedResults());
    const mapSvg = container.querySelector('.map svg');
    expect(mapSvg?.querySelectorAll('polygon').length).toBe(1);
    expect(mapSvg?.querySelector('line[stroke="#00b84a"]')).toBeTruthy();
    expect(mapSvg?.querySelector('line[stroke="#ff5a1f"]')).toBeTruthy();
    const children = Array.from(mapSvg?.children ?? []);
    expect(children.findIndex((child) => child.tagName === 'polygon')).toBeLessThan(
      children.findIndex((child) => child.tagName === 'polyline'),
    );
    expect(container.textContent).toContain('나무 그늘 미포함');
  });
});
