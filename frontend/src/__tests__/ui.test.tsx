// @vitest-environment jsdom
/**
 * UI 상태 테스트 (요구사항 §12).
 * - 첫 화면에서 지도보다 검색창이 먼저 렌더링되는가
 * - 프로필 칩 6개가 보이는가
 * - 음성 챗봇이 하단(문서 마지막)에 고정 영역으로 존재하는가
 * - 경로 검색 후 활성 MapView와 RouteCards가 인접하게 표시되는가
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render } from '@testing-library/react';
import App from '@/App';
import { useAppStore } from '@/store/appStore';
import { recommendRoutes } from '@/scoring/engine';
import { demoCandidates } from '@/data/routes';
import { WEATHER_SCENARIOS } from '@/data/weather';
import { findPlace } from '@/data/places';
import { adapters } from '@/adapters';
import type { ScoredRoute } from '@/types';

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

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
    profile: 'general',
    origin: null,
    destination: null,
    candidates: [],
    recommendations: [],
    selectedRouteId: null,
    options: {},
    largeUi: false,
    loading: false,
    error: null,
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
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

  it('프로필 칩 6개가 보인다', () => {
    const { container } = render(<App />);
    expect(container.querySelectorAll('[role="radio"]').length).toBe(6);
    expect(container.textContent).toContain('청소년');
    expect(container.textContent).toContain('임산부');
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

  it('경로 검색 후 활성 MapView가 RouteCards 바로 앞에 표시된다', () => {
    const { container } = render(<App />);
    act(() => seedResults());
    const routeCard = container.querySelector('.route-card');
    const map = container.querySelector('.map');
    expect(routeCard).toBeTruthy();
    expect(map).toBeTruthy(); // 결과가 생기면 지도 자동 확장
    expect(precedes(map!, routeCard!)).toBe(true);
    expect(map!.closest('.results')).toBe(routeCard!.closest('.results'));
  });

  it('경로 카드에는 점수 종류를 명시한 비교 적합 점수와 사실 특성을 표시한다', () => {
    const { container } = render(<App />);
    act(() => seedResults());
    expect(container.querySelector('.route-card__score')?.textContent)
      .toContain('규칙 베이스라인 적합 점수');
    expect(container.textContent).toContain('안전도나 성공 확률이 아닙니다');
    expect(container.querySelector('.route-card__stats')?.textContent).toMatch(/분.*도보.*환승/);
  });

  it('그늘을 계산할 수 없으면 0% 대신 정보 없음과 계산 사유를 표시한다', () => {
    const { container } = render(<App />);
    act(() => {
      seedResults();
      const [first, ...rest] = useAppStore.getState().recommendations;
      const updated = {
        ...first,
        route: {
          ...first.route,
          shade: {
            status: 'unavailable' as const,
            evaluatedAt: '2026-07-24T14:00:00+09:00',
            source: '검증용 데모 건물 높이 데이터',
            dataQuality: 'demo' as const,
            shadowPolygons: [],
            pathSegments: [],
            calculationNote: '선택한 경로가 건물 데이터의 검증 범위를 벗어났습니다.',
          },
        },
      };
      useAppStore.setState({
        recommendations: [updated, ...rest],
        candidates: [updated.route, ...rest.map((item) => item.route)],
      });
    });

    const routeId = useAppStore.getState().recommendations[0].route.id;
    const card = container.querySelector(`[data-route-id="${routeId}"]`)!;
    expect(card.textContent).toContain('건물 그늘 정보 없음');
    expect(card.textContent).toContain('건물 데이터의 검증 범위를 벗어났습니다');
    expect(card.textContent).not.toContain('건물 그늘 0%');
  });

  it('일부 구간만 계단 없음이면 전체 경로를 계단 없음으로 단정하지 않는다', () => {
    const { container } = render(<App />);
    act(() => {
      seedResults();
      const [first, ...rest] = useAppStore.getState().recommendations;
      const knownWalk = {
        ...first.route.segments.find((segment) => segment.mode === 'walk')!,
        hasStairs: false,
        stairsCount: 0,
        needsVerticalMove: undefined,
      };
      const unknownWalk = {
        ...knownWalk,
        id: 'unknown-walk-evidence',
        hasStairs: undefined,
        stairsCount: undefined,
      };
      const updated = {
        ...first,
        route: {
          ...first.route,
          characteristics: (first.route.characteristics ?? []).filter(
            (value) => value !== 'stair_free',
          ),
          segments: [knownWalk, unknownWalk],
        },
      };
      useAppStore.setState({
        recommendations: [updated, ...rest],
        candidates: [updated.route, ...rest.map((item) => item.route)],
      });
    });
    const routeId = useAppStore.getState().recommendations[0].route.id;
    const card = container.querySelector(`[data-route-id="${routeId}"]`)!;
    expect(card.textContent).toContain('계단 정보 미확인');
    expect(card.textContent).toContain('수직이동 정보 미확인');
    expect(card.textContent).not.toContain('계단 없음 확인');
  });

  it('hasStairs가 없어도 양수 stairsCount는 계단 있음으로 표시한다', () => {
    const { container } = render(<App />);
    act(() => {
      seedResults();
      const [first, ...rest] = useAppStore.getState().recommendations;
      const segment = {
        ...first.route.segments.find((item) => item.mode === 'walk')!,
        hasStairs: undefined,
        stairsCount: 3,
      };
      const updated = {
        ...first,
        route: {
          ...first.route,
          characteristics: (first.route.characteristics ?? []).filter(
            (value) => value !== 'stair_free',
          ),
          segments: [segment],
        },
      };
      useAppStore.setState({
        recommendations: [updated, ...rest],
        candidates: [updated.route, ...rest.map((item) => item.route)],
      });
    });
    const routeId = useAppStore.getState().recommendations[0].route.id;
    const card = container.querySelector(`[data-route-id="${routeId}"]`)!;
    expect(card.textContent).toContain('계단 3개');
  });

  it('경로 카드는 점수순 스와이프 목록이며 다음 버튼과 키보드로 지도 선택 경로를 바꾼다', () => {
    const { container, getByLabelText } = render(<App />);
    act(() => seedResults());
    const ranked = [...useAppStore.getState().recommendations].sort(
      (a, b) => b.score.finalScore - a.score.finalScore
        || a.route.totalDurationMin - b.route.totalDurationMin,
    );
    const cards = Array.from(container.querySelectorAll<HTMLElement>('.route-card'));
    expect(cards.map((card) => card.dataset.routeId)).toEqual(
      ranked.map(({ route }) => route.id),
    );
    expect(container.querySelector('.route-carousel__viewport')).toBeTruthy();

    fireEvent.click(getByLabelText('다음 경로 보기'));
    expect(useAppStore.getState().selectedRouteId).toBe(ranked[1].route.id);
    expect(container.querySelector('.route-carousel__position')?.textContent).toContain('2');

    fireEvent.keyDown(container.querySelector('.route-carousel__viewport')!, { key: 'End' });
    expect(useAppStore.getState().selectedRouteId).toBe(ranked[ranked.length - 1].route.id);

    const mapRouteButtons = container.querySelectorAll<HTMLButtonElement>('.map__route-picker button');
    fireEvent.click(mapRouteButtons[0]);
    expect(useAppStore.getState().selectedRouteId).toBe(ranked[0].route.id);
    expect(
      container.querySelector(`[data-route-id="${ranked[0].route.id}"]`)
        ?.classList.contains('route-card--selected'),
    ).toBe(true);

    const listenButton = container.querySelector<HTMLButtonElement>('.route-card .btn--listen')!;
    fireEvent.keyDown(listenButton, { key: 'ArrowRight' });
    expect(useAppStore.getState().selectedRouteId).toBe(ranked[0].route.id);
  });

  it('출발지나 도착지가 바뀌면 이전 OD의 경로·지도 결과를 즉시 폐기한다', () => {
    const { container } = render(<App />);
    act(() => seedResults());
    expect(container.querySelectorAll('.route-card')).not.toHaveLength(0);

    act(() => useAppStore.getState().setDestination(null));

    expect(useAppStore.getState()).toMatchObject({
      candidates: [],
      recommendations: [],
      selectedRouteId: null,
      loading: false,
      error: null,
    });
    expect(container.querySelector('.route-card')).toBeNull();
    expect(container.querySelector('.map')).toBeNull();
  });

  it('지도 데이터 출처는 응답에 실제 포함된 공급자만 표시한다', () => {
    vi.stubEnv('VITE_KAKAO_MAP_KEY', '');
    const { container } = render(<App />);
    act(() => {
      seedResults();
      const [first, ...rest] = useAppStore.getState().recommendations;
      const updated = {
        ...first,
        route: {
          ...first.route,
          sources: ['odsay'],
          geometryQuality: 'mixed' as const,
          terrain: { status: 'unavailable' as const },
        },
      };
      useAppStore.setState({
        recommendations: [updated, ...rest],
        candidates: [updated.route, ...rest.map((item) => item.route)],
      });
    });

    const note = container.querySelector('.map .map__note:last-child')?.textContent ?? '';
    expect(note).toContain('경로: odsay');
    expect(note).toContain('지도: 내장 경로 약도');
    expect(note).not.toContain('Copernicus');
    expect(note).not.toContain('Open-Meteo');
    expect(note).not.toContain('OpenStreetMap');
  });

  it('AI 평가 베이스라인 점수 종류를 구분해서 표시한다', () => {
    const { container } = render(<App />);
    act(() => {
      seedResults();
      const recommendations = useAppStore.getState().recommendations.map((item, index) => (
        index === 0
          ? { ...item, score: { ...item.score, scoreKind: 'judge_baseline' as const } }
          : item
      ));
      useAppStore.setState({ recommendations });
    });
    expect(container.textContent).toContain('AI 평가 베이스라인 적합 점수');
  });

  it('이번 이동 조건 6개를 켜고 끌 수 있다', () => {
    const { container, getByRole } = render(<App />);
    expect(container.querySelectorAll('.condition-chip')).toHaveLength(6);
    const stroller = getByRole('button', { name: /유아차 이용/ });
    const shade = getByRole('button', { name: /건물 그늘 우선/ });
    const transfer = getByRole('button', { name: /환승 최소/ });
    fireEvent.click(stroller);
    fireEvent.click(shade);
    fireEvent.click(transfer);
    expect(useAppStore.getState().options).toMatchObject({
      stroller: true,
      shadePriority: true,
      minimizeTransfers: true,
    });
    fireEvent.click(stroller);
    expect(useAppStore.getState().options.stroller).toBe(false);
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

  it('느린 이전 검색 성공 응답이 빠른 최신 재채점 결과를 덮어쓰지 않는다', async () => {
    seedResults();
    const baseline = useAppStore.getState().recommendations;
    const previous = deferred<ScoredRoute[]>();
    const latest = deferred<ScoredRoute[]>();
    const previousRecommendations = baseline.map((item) => ({
      ...item,
      score: { ...item.score, finalScore: 0.11 },
    }));
    const latestRecommendations = baseline.map((item) => ({
      ...item,
      score: { ...item.score, finalScore: 0.91 },
    }));
    vi.spyOn(adapters.routes, 'recommend')
      .mockImplementationOnce(() => previous.promise)
      .mockImplementationOnce(() => latest.promise);

    const previousRequest = useAppStore.getState().search();
    const latestRequest = useAppStore.getState().rescore();
    latest.resolve(latestRecommendations);
    await latestRequest;

    expect(useAppStore.getState()).toMatchObject({
      recommendations: latestRecommendations,
      loading: false,
      error: null,
    });

    previous.resolve(previousRecommendations);
    await previousRequest;
    expect(useAppStore.getState()).toMatchObject({
      recommendations: latestRecommendations,
      loading: false,
      error: null,
    });
  });

  it('검색 중 목적지가 바뀌면 이전 OD 응답을 화면에 반영하지 않는다', async () => {
    seedResults();
    const previous = deferred<ScoredRoute[]>();
    const previousRecommendations = useAppStore.getState().recommendations;
    vi.spyOn(adapters.routes, 'recommend').mockImplementationOnce(() => previous.promise);

    const request = useAppStore.getState().search();
    useAppStore.getState().setDestination(null);
    previous.resolve(previousRecommendations);
    await request;

    expect(useAppStore.getState()).toMatchObject({
      destination: null,
      candidates: [],
      recommendations: [],
      selectedRouteId: null,
      loading: false,
      error: null,
    });
  });

  it('초기 검색 중 날씨 조건이 바뀌면 이전 검색을 취소하고 새 조건으로 다시 검색한다', async () => {
    seedResults();
    const baseline = useAppStore.getState().recommendations;
    const previous = deferred<ScoredRoute[]>();
    const rainRecommendations = baseline.map((item) => ({
      ...item,
      score: { ...item.score, finalScore: item.score.finalScore + 0.5 },
    }));
    useAppStore.setState({
      candidates: [],
      recommendations: [],
      selectedRouteId: null,
      loading: false,
    });
    const routes = vi.spyOn(adapters.routes, 'recommend')
      .mockImplementationOnce(() => previous.promise)
      .mockResolvedValueOnce(rainRecommendations);
    vi.spyOn(adapters.weather, 'getCurrent')
      .mockResolvedValue(WEATHER_SCENARIOS.rain);

    const initialSearch = useAppStore.getState().search();
    await useAppStore.getState().setWeatherScenario('rain');
    previous.resolve(baseline);
    await initialSearch;

    expect(routes).toHaveBeenCalledTimes(2);
    expect(routes.mock.calls[1][3]).toBe('rain');
    expect(useAppStore.getState()).toMatchObject({
      weatherScenario: 'rain',
      weather: WEATHER_SCENARIOS.rain,
      recommendations: rainRecommendations,
      loading: false,
      error: null,
    });
  });

  it('느린 이전 재채점 실패가 최신 성공 뒤의 오류·로딩 상태를 바꾸지 않는다', async () => {
    seedResults();
    const baseline = useAppStore.getState().recommendations;
    const previous = deferred<ScoredRoute[]>();
    const latest = deferred<ScoredRoute[]>();
    const latestRecommendations = baseline.map((item) => ({
      ...item,
      score: { ...item.score, finalScore: 0.87 },
    }));
    vi.spyOn(adapters.routes, 'recommend')
      .mockImplementationOnce(() => previous.promise)
      .mockImplementationOnce(() => latest.promise);

    const previousRequest = useAppStore.getState().rescore();
    const latestRequest = useAppStore.getState().rescore();
    latest.resolve(latestRecommendations);
    await latestRequest;
    previous.reject(new Error('느린 이전 요청 실패'));
    await previousRequest;

    expect(useAppStore.getState()).toMatchObject({
      recommendations: latestRecommendations,
      loading: false,
      error: null,
    });
  });
});
