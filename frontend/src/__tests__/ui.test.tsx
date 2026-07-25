// @vitest-environment jsdom
/**
 * 프로덕션 v2 지도 중심 UI 상태 테스트.
 *
 * 카카오 SDK 자체의 도형 렌더링은 SDK 단위 테스트의 책임으로 두고, 여기서는
 * MapFirstApp → KakaoMap 데이터/선택/그늘 표시 계약을 작은 지도 대역으로 검증한다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  act,
  cleanup,
  fireEvent,
  render,
  waitFor,
  within,
} from '@testing-library/react';
import App from '@/App';
import { adapters } from '@/adapters';
import { useVoiceChatStore } from '@/chat/voiceChatStore';
import { findPlace } from '@/data/places';
import { demoCandidates } from '@/data/routes';
import { WEATHER_SCENARIOS } from '@/data/weather';
import { recommendRoutes } from '@/scoring/engine';
import { useAppStore } from '@/store/appStore';
import type { ScoredRoute } from '@/types';

vi.mock('@/v2/KakaoMap', () => ({
  default: ({
    recommendations,
    selectedRouteId,
    onSelectRoute,
    showShade,
    showFacilities,
  }: {
    recommendations: ScoredRoute[];
    selectedRouteId: string | null;
    onSelectRoute: (routeId: string) => void;
    showShade: boolean;
    showFacilities?: boolean;
  }) => {
    const selected = recommendations.find(
      ({ route }) => route.id === selectedRouteId,
    );
    const shade = selected?.route.shade;
    const overlayVisible =
      showShade &&
      (shade?.status === 'estimated_demo' ||
        shade?.status === 'estimated_public');

    return (
      <section
        className="map-first__map map-first__map--test"
        role="region"
        aria-label="지도"
        data-selected-route-id={selectedRouteId ?? ''}
        data-route-count={recommendations.length}
        data-shade-visible={showShade}
        data-facilities-visible={showFacilities}
        data-shadow-polygons={
          overlayVisible ? shade?.shadowPolygons.length ?? 0 : 0
        }
        data-path-segments={
          overlayVisible ? shade?.pathSegments.length ?? 0 : 0
        }
      >
        {recommendations.map(({ route }, index) => (
          <button
            key={route.id}
            type="button"
            className="map-first__map-route"
            aria-label={`지도에서 ${index + 1}순위 경로 선택`}
            aria-pressed={route.id === selectedRouteId}
            onClick={() => onSelectRoute(route.id)}
          >
            {route.summary}
          </button>
        ))}
      </section>
    );
  },
}));

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

/** a가 문서상 b보다 앞에 있으면 true */
function precedes(a: Element, b: Element): boolean {
  return Boolean(
    a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING,
  );
}

function seedResults() {
  const candidates = demoCandidates();
  const weather = WEATHER_SCENARIOS.normal;
  const recommendations = recommendRoutes(
    candidates,
    weather,
    'general',
  );
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
            {
              start: end,
              end: path[2] ?? end,
              shaded: false,
            },
          ],
          calculationNote: '테스트',
        },
      },
    };
  });
  useAppStore.setState({ recommendations });
}

function openSelectedRouteDetails(container: HTMLElement) {
  const selected =
    container.querySelector<HTMLElement>(
      '.map-first__route-card--selected',
    ) ?? container.querySelector<HTMLElement>('.map-first__route-card');
  const details = selected?.querySelector<HTMLButtonElement>(
    '.map-first__sheet-cta',
  );
  expect(details).toBeTruthy();
  fireEvent.click(details!);
  return container.querySelector<HTMLElement>(
    '[aria-label="선택 경로 상세"]',
  );
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
  useVoiceChatStore.setState({
    status: 'idle',
    interim: '',
    awaiting: null,
    profileConfirmed: false,
    lastGuide: '',
    listenRequestId: 0,
  });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('프로덕션 v2 지도 중심 UI', () => {
  it('첫 화면은 지도 위에 카카오 장소 선택 입력을 제공한다', () => {
    const { container, getByLabelText, getByRole } = render(<App />);
    const map = getByRole('region', { name: '지도' });
    const search = container.querySelector('.map-first__search');

    expect(container.querySelector('.map-first__frame')).toBeTruthy();
    expect(search).toBeTruthy();
    expect(precedes(map, search!)).toBe(true);
    expect(getByLabelText('출발지').getAttribute('placeholder')).toBe(
      '출발지 검색',
    );
    expect(getByLabelText('도착지').getAttribute('placeholder')).toBe(
      '도착지 검색',
    );
    expect(getByRole('button', { name: '경로 찾기' })).toBeTruthy();
  });

  it('장소명 입력은 카카오 장소 어댑터 결과를 선택된 Place로 저장한다', async () => {
    const place = findPlace('gu-office')!;
    const searchPlaces = vi
      .spyOn(adapters.places, 'searchPlaces')
      .mockResolvedValue([place]);
    const { getByLabelText, getByRole } = render(<App />);

    fireEvent.change(getByLabelText('출발지'), {
      target: { value: '북구청' },
    });

    await waitFor(() => {
      expect(searchPlaces).toHaveBeenCalledWith('북구청');
    });
    fireEvent.click(
      getByRole('option', {
        name: new RegExp(place.name),
      }),
    );

    expect(useAppStore.getState().origin?.id).toBe(place.id);
    expect(
      (getByLabelText('출발지') as HTMLInputElement).value,
    ).toBe(place.name);
  });

  it('프로필 drawer에서 6개 프로필을 선택할 수 있다', () => {
    const { container, getByRole } = render(<App />);
    expect(container.querySelector('[role="radiogroup"]')).toBeNull();

    fireEvent.click(
      getByRole('button', {
        name: /프로필 선택, 현재/,
      }),
    );

    expect(
      getByRole('dialog', { name: '이동 프로필 선택' }),
    ).toBeTruthy();
    expect(container.querySelectorAll('[role="radio"]')).toHaveLength(6);
    expect(container.textContent).toContain('청소년');
    expect(container.textContent).toContain('임산부');
    fireEvent.click(getByRole('radio', { name: /임산부/ }));
    expect(useAppStore.getState().profile).toBe('pregnant');
  });

  it('검색 전에는 데모 경로나 수치를 자동으로 표시하지 않는다', () => {
    const { container, getByText, getByRole } = render(<App />);

    expect(useAppStore.getState()).toMatchObject({
      origin: null,
      destination: null,
      candidates: [],
      recommendations: [],
      selectedRouteId: null,
    });
    expect(container.querySelector('.map-first__route-card')).toBeNull();
    expect(
      getByText(
        '검색 전에는 경로 수치나 편의 특성을 표시하지 않습니다.',
      ),
    ).toBeTruthy();
    expect(
      getByRole('region', { name: '지도' }).getAttribute(
        'data-route-count',
      ),
    ).toBe('0');
  });

  it('지도 음성 버튼은 실제 map-first VoiceChatDock을 연다', async () => {
    const { queryByRole, getByRole, findByRole } = render(<App />);
    expect(
      queryByRole('region', { name: '음성 챗봇' }),
    ).toBeNull();

    fireEvent.click(getByRole('button', { name: '음성 챗봇' }));

    const dock = await findByRole('region', { name: '음성 챗봇' });
    expect(dock.classList.contains('voicedock--map-first')).toBe(true);
    expect(
      getByRole('button', { name: '음성 챗봇 닫기' }),
    ).toBeTruthy();
    expect(
      getByRole('textbox', { name: '챗봇 텍스트 입력' }),
    ).toBeTruthy();
    expect(useVoiceChatStore.getState().listenRequestId).toBe(1);
  });

  it('결과 카드는 점수 종류·비교 한계·확인된 사실만 표시한다', () => {
    const { container, getByRole } = render(<App />);
    act(() => seedResults());

    expect(
      getByRole('heading', {
        name: `추천 경로 ${useAppStore.getState().recommendations.length}개`,
      }),
    ).toBeTruthy();
    expect(
      container.querySelector('.map-first__route-score')?.textContent,
    ).toContain('프로필 적합 점수');
    expect(container.textContent).toContain(
      '안전도나 성공 확률이 아닙니다',
    );
    expect(
      container.querySelector('.map-first__route-stats')?.textContent,
    ).toMatch(/분.*m 도보.*회 환승/);
    expect(
      getByRole('region', { name: '지도' }).getAttribute(
        'data-selected-route-id',
      ),
    ).toBe(useAppStore.getState().selectedRouteId);
  });

  it('그늘을 계산할 수 없으면 0%가 아니라 미확인과 계산 사유를 표시한다', () => {
    const { container } = render(<App />);
    act(() => {
      seedResults();
      const [first, ...rest] =
        useAppStore.getState().recommendations;
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
            calculationNote:
              '선택한 경로가 건물 데이터의 검증 범위를 벗어났습니다.',
          },
        },
      };
      useAppStore.setState({
        recommendations: [updated, ...rest],
        candidates: [
          updated.route,
          ...rest.map((item) => item.route),
        ],
      });
    });

    const details = openSelectedRouteDetails(container);
    expect(details?.textContent).toContain('건물 그늘 정보 없음');
    expect(details?.textContent).toContain(
      '건물 데이터의 검증 범위를 벗어났습니다',
    );
    expect(details?.textContent).not.toContain('건물 그늘 0%');
  });

  it('부분 계단 없음 증거로 전체 경로를 계단 없음이라고 단정하지 않는다', () => {
    const { container } = render(<App />);
    act(() => {
      seedResults();
      const [first, ...rest] =
        useAppStore.getState().recommendations;
      const knownWalk = {
        ...first.route.segments.find(
          (segment) => segment.mode === 'walk',
        )!,
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
        score: {
          ...first.score,
          lowFloorStatus: 'unknown' as const,
        },
        route: {
          ...first.route,
          characteristics: (
            first.route.characteristics ?? []
          ).filter((value) => value !== 'stair_free'),
          segments: [knownWalk, unknownWalk],
        },
      };
      useAppStore.setState({
        recommendations: [updated, ...rest],
        candidates: [
          updated.route,
          ...rest.map((item) => item.route),
        ],
      });
    });

    const details = openSelectedRouteDetails(container);
    expect(details?.textContent).toContain('계단 정보 미확인');
    expect(details?.textContent).toContain('수직이동 정보 미확인');
    expect(details?.textContent).toContain('저상 여부 미확인');
    expect(details?.textContent).not.toContain('계단 없음 확인');
  });

  it('hasStairs가 없어도 양수 stairsCount는 계단 있음으로 표시한다', () => {
    const { container } = render(<App />);
    act(() => {
      seedResults();
      const [first, ...rest] =
        useAppStore.getState().recommendations;
      const segment = {
        ...first.route.segments.find(
          (item) => item.mode === 'walk',
        )!,
        hasStairs: undefined,
        stairsCount: 3,
      };
      const updated = {
        ...first,
        route: {
          ...first.route,
          characteristics: (
            first.route.characteristics ?? []
          ).filter((value) => value !== 'stair_free'),
          segments: [segment],
        },
      };
      useAppStore.setState({
        recommendations: [updated, ...rest],
        candidates: [
          updated.route,
          ...rest.map((item) => item.route),
        ],
      });
    });

    const details = openSelectedRouteDetails(container);
    expect(details?.textContent).toContain('계단 3개');
  });

  it('서버 순위 카드와 지도 선택이 동기화되고 스크롤·버튼·키보드로 이동한다', async () => {
    const { container, getByLabelText, getByRole } = render(<App />);
    act(() => seedResults());
    const ranked = useAppStore.getState().recommendations;
    const cards = Array.from(
      container.querySelectorAll<HTMLElement>(
        '.map-first__route-card',
      ),
    );
    expect(cards.map((card) => card.dataset.routeId)).toEqual(
      ranked.map(({ route }) => route.id),
    );

    const viewport = container.querySelector<HTMLElement>(
      '.map-first__route-viewport',
    )!;
    fireEvent.click(getByLabelText('다음 경로 보기'));
    expect(useAppStore.getState().selectedRouteId).toBe(
      ranked[1].route.id,
    );
    // 브라우저의 즉시 스크롤 이벤트가 프로그램 선택을 첫 카드로
    // 되돌리지 않아야 한다.
    fireEvent.scroll(viewport);
    await act(
      () =>
        new Promise<void>((resolve) => {
          window.setTimeout(resolve, 220);
        }),
    );
    expect(useAppStore.getState().selectedRouteId).toBe(
      ranked[1].route.id,
    );
    expect(
      getByRole('region', { name: '지도' }).getAttribute(
        'data-selected-route-id',
      ),
    ).toBe(ranked[1].route.id);

    fireEvent.keyDown(viewport, { key: 'End' });
    expect(useAppStore.getState().selectedRouteId).toBe(
      ranked[ranked.length - 1].route.id,
    );

    fireEvent.click(
      getByLabelText('지도에서 1순위 경로 선택'),
    );
    expect(useAppStore.getState().selectedRouteId).toBe(
      ranked[0].route.id,
    );
    expect(
      container
        .querySelector(
          `[data-route-id="${ranked[0].route.id}"]`,
        )
        ?.classList.contains('map-first__route-card--selected'),
    ).toBe(true);

    Object.defineProperty(viewport, 'clientWidth', {
      configurable: true,
      value: 300,
    });
    const positions = [-160, 110, 380, 650];
    vi.spyOn(
      HTMLElement.prototype,
      'getBoundingClientRect',
    ).mockImplementation(function mockRect(this: HTMLElement) {
      const routeIndex = ranked.findIndex(
        ({ route }) => route.id === this.dataset.routeId,
      );
      const left =
        this === viewport
          ? 0
          : routeIndex >= 0
            ? positions[routeIndex]
            : 0;
      const width = this === viewport ? 300 : 80;
      return {
        left,
        width,
        right: left + width,
        top: 0,
        bottom: 100,
        height: 100,
        x: left,
        y: 0,
        toJSON: () => ({}),
      } as DOMRect;
    });
    const requestFrame = vi
      .spyOn(globalThis, 'requestAnimationFrame')
      .mockImplementation(
      (callback) => {
        callback(0);
        return 1;
      },
      );
    expect(
      Array.from(
        viewport.querySelectorAll<HTMLElement>('[data-route-id]'),
      ).map((card) => ({
        id: card.dataset.routeId,
        left: card.getBoundingClientRect().left,
      })),
    ).toEqual(
      ranked.map(({ route }, index) => ({
        id: route.id,
        left: positions[index],
      })),
    );
    expect(viewport.isConnected).toBe(true);
    fireEvent.pointerDown(viewport);
    fireEvent.scroll(viewport);
    expect(requestFrame).toHaveBeenCalled();
    await waitFor(() => {
      expect(useAppStore.getState().selectedRouteId).toBe(
        ranked[1].route.id,
      );
    });

    fireEvent.keyDown(viewport, { key: 'ArrowLeft' });
    expect(useAppStore.getState().selectedRouteId).toBe(
      ranked[0].route.id,
    );
  });

  it('출발지나 도착지가 바뀌면 이전 OD의 카드·지도 경로를 즉시 폐기한다', () => {
    const { container, getByRole } = render(<App />);
    act(() => seedResults());
    expect(
      container.querySelectorAll('.map-first__route-card'),
    ).not.toHaveLength(0);

    act(() => useAppStore.getState().setDestination(null));

    expect(useAppStore.getState()).toMatchObject({
      candidates: [],
      recommendations: [],
      selectedRouteId: null,
      loading: false,
      error: null,
    });
    expect(
      container.querySelector('.map-first__route-card'),
    ).toBeNull();
    expect(
      getByRole('region', { name: '지도' }).getAttribute(
        'data-route-count',
      ),
    ).toBe('0');
  });

  it('경로 상세는 응답에 실제 포함된 공급자만 표시한다', () => {
    const { container } = render(<App />);
    act(() => {
      seedResults();
      const [first, ...rest] =
        useAppStore.getState().recommendations;
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
        candidates: [
          updated.route,
          ...rest.map((item) => item.route),
        ],
      });
    });

    const details = openSelectedRouteDetails(container);
    const text = details?.textContent ?? '';
    expect(text).toContain('odsay');
    expect(text).toContain('실제·추정 형상 혼합');
    expect(text).not.toContain('Copernicus');
    expect(text).not.toContain('Open-Meteo');
    expect(text).not.toContain('OpenStreetMap');
  });

  it('내부 점수 구현과 무관하게 프로필 적합 점수로 표시한다', () => {
    const { container } = render(<App />);
    act(() => {
      seedResults();
      const recommendations =
        useAppStore.getState().recommendations.map(
          (item, index) =>
            index === 0
              ? {
                  ...item,
                  score: {
                    ...item.score,
                    scoreKind: 'bootstrap_baseline' as const,
                  },
                }
              : item,
        );
      useAppStore.setState({ recommendations });
    });
    expect(container.textContent).toContain(
      '프로필 적합 점수',
    );
  });

  it('조건 drawer에 6개 이동 조건이 있고 점수 옵션을 켜고 끈다', () => {
    const { container, getByRole } = render(<App />);
    const quickLuggage = getByRole('button', { name: '짐 많음' });
    const quickStairs = getByRole('button', { name: '계단 회피' });
    const easyScreen = getByRole('button', { name: '쉬운 화면' });
    expect(quickLuggage).toBeTruthy();
    expect(quickStairs).toBeTruthy();
    expect(easyScreen).toBeTruthy();

    fireEvent.click(quickLuggage);
    expect(useAppStore.getState().options.carryLuggage).toBe(true);
    fireEvent.click(getByRole('button', { name: /^조건/ }));

    const dialog = getByRole('dialog', { name: '이번 이동 조건' });
    const dialogQueries = within(dialog);
    expect(dialog).toBeTruthy();
    expect(container.querySelectorAll('.condition-chip')).toHaveLength(
      6,
    );
    expect(
      dialogQueries.getByRole('button', { name: /짐 많음/ })
        .getAttribute('aria-pressed'),
    ).toBe('true');
    expect(
      dialogQueries.getByRole('button', { name: /계단 회피/ }),
    ).toBeTruthy();
    const stroller = dialogQueries.getByRole('button', { name: /유아차 이용/ });
    const shade = dialogQueries.getByRole('button', { name: /건물 그늘 우선/ });
    const transfer = dialogQueries.getByRole('button', { name: /환승 최소/ });
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

  it('활성 조건이 생겨도 조건 버튼 폭과 접근 가능한 이름이 안정적이다', () => {
    const { getByRole } = render(<App />);
    const conditions = getByRole('button', { name: '조건' });
    const widthBefore = conditions.getBoundingClientRect().width;

    fireEvent.click(conditions);
    const dialog = getByRole('dialog', { name: '이번 이동 조건' });
    fireEvent.click(
      within(dialog).getByRole('button', { name: /짐 많음/ }),
    );
    fireEvent.keyDown(dialog, {
      key: 'Escape',
    });

    const updated = getByRole('button', { name: '조건, 활성 1개' });
    expect(updated.textContent).toContain('1');
    expect(
      Math.abs(updated.getBoundingClientRect().width - widthBefore),
    ).toBeLessThanOrEqual(1);
    expect(document.documentElement.scrollWidth).toBe(
      document.documentElement.clientWidth,
    );
  });

  it('경로 결과가 있을 때만 출발 시간 버튼을 보이고 적용 시에만 setDepartureAt을 호출한다', async () => {
    const { getByRole, queryByRole } = render(<App />);
    expect(queryByRole('button', { name: '지금 출발' })).toBeNull();

    act(() => seedResults());
    const before = useAppStore.getState().options.departureAt;
    const recommend = vi.spyOn(adapters.routes, 'recommend');
    const refreshShade = vi
      .spyOn(adapters.routes, 'refreshShade')
      .mockResolvedValue(useAppStore.getState().recommendations);

    expect(getByRole('button', { name: '지금 출발' })).toBeTruthy();
    fireEvent.click(getByRole('button', { name: '지금 출발' }));
    expect(getByRole('dialog', { name: '출발 시간 설정' })).toBeTruthy();

    fireEvent.click(getByRole('button', { name: '오후 2시' }));
    expect(useAppStore.getState().options.departureAt).toBe(before);
    expect(refreshShade).not.toHaveBeenCalled();

    fireEvent.click(getByRole('button', { name: '적용' }));
    await waitFor(() => {
      expect(refreshShade).toHaveBeenCalledOnce();
      expect(queryByRole('dialog', { name: '출발 시간 설정' })).toBeNull();
    });
    expect(useAppStore.getState().options.departureAt).toMatch(/T14:00/);
    expect(getByRole('button', { name: '출발 오후 2:00' })).toBeTruthy();
    expect(recommend).not.toHaveBeenCalled();
  });

  it('그늘 갱신 중 상태를 알리고 실패하면 이전 출발 시간과 결과를 유지한다', async () => {
    const { getByRole } = render(<App />);
    act(() => seedResults());
    const beforeDepartureAt = useAppStore.getState().options.departureAt;
    const beforeRecommendations = useAppStore.getState().recommendations;
    const pending = deferred<ScoredRoute[]>();
    vi.spyOn(adapters.routes, 'refreshShade').mockReturnValue(pending.promise);

    fireEvent.click(getByRole('button', { name: '지금 출발' }));
    fireEvent.click(getByRole('button', { name: '오후 2시' }));
    fireEvent.click(getByRole('button', { name: '적용' }));

    expect(
      getByRole('button', { name: '계산 중…' }).hasAttribute('disabled'),
    ).toBe(true);
    expect(
      getByRole('region', { name: '출발 시간 설정 내용' })
        .getAttribute('aria-busy'),
    ).toBe('true');

    pending.reject(new Error('그늘 갱신 실패'));
    await waitFor(() => {
      expect(getByRole('button', { name: '적용' })).toBeTruthy();
      expect(useAppStore.getState().options.departureAt).toBe(beforeDepartureAt);
    });
    expect(useAppStore.getState().recommendations).toEqual(beforeRecommendations);
    expect(
      getByRole('dialog', { name: '출발 시간 설정' }),
    ).toBeTruthy();
  });

  it('그늘 legend와 지도 오버레이 계약은 선택 경로·토글과 동기화된다', () => {
    const { container, getByRole } = render(<App />);
    act(() => seedShadedResults());

    const map = getByRole('region', { name: '지도' });
    expect(map.getAttribute('data-shadow-polygons')).toBe('1');
    expect(map.getAttribute('data-path-segments')).toBe('2');
    expect(
      container.querySelector('.map-first__map-legend')?.textContent,
    ).toMatch(/건물 그늘 50%.*그늘.*햇빛.*데모 높이/);

    fireEvent.click(
      getByRole('button', { name: '건물 그늘 오버레이' }),
    );
    expect(map.getAttribute('data-shade-visible')).toBe('false');
    expect(map.getAttribute('data-shadow-polygons')).toBe('0');
    expect(container.querySelector('.map-first__map-legend')).toBeNull();

    fireEvent.click(getByRole('button', { name: '건물 그늘 오버레이' }));
    expect(
      getByRole('button', { name: /편의시설 오버레이/ }),
    ).toBeTruthy();
    expect(container.textContent).not.toContain('API 연결 모드');
    expect(container.textContent).not.toContain('검증용 내장 데이터');
  });

  it('시설 정보는 있지만 segment 좌표가 없으면 안내만 보이고 오버레이는 켜지지 않는다', () => {
    const { getByRole, queryByRole } = render(<App />);
    act(() => {
      seedResults();
      const withInfo = useAppStore.getState().recommendations.find(({ route }) =>
        route.segments.some(
          (segment) =>
            (segment.mode === 'subway' && segment.hasElevator === true) ||
            (segment.mode === 'bus' && segment.isLowFloorBus === true),
        ),
      );
      expect(withInfo).toBeTruthy();
      useAppStore.setState({ selectedRouteId: withInfo!.route.id });
    });

    const map = getByRole('region', { name: '지도' });
    const facility = getByRole('button', {
      name: '편의시설 오버레이, 위치 데이터 없음',
    });
    expect(facility).toBeTruthy();
    expect(facility.hasAttribute('disabled')).toBe(false);

    fireEvent.click(facility);
    expect(
      document.querySelector('.map-first__fab-hint')?.textContent,
    ).toContain('지도에 표시할 위치 데이터가 없어요');
    expect(
      document.querySelector('.map-first__fab-hint')?.getAttribute('role'),
    ).toBe('status');
    expect(map.getAttribute('data-facilities-visible')).toBe('false');
    expect(facility.getAttribute('aria-pressed')).toBeNull();
    expect(queryByRole('button', { name: '음성 챗봇' })).toBeNull();
  });

  it('시설 overlay 좌표가 있으면 편의시설 버튼을 토글할 수 있다', () => {
    const { getByRole } = render(<App />);
    act(() => {
      seedResults();
      const recommendations = useAppStore.getState().recommendations.map(
        (item) => {
          const fallbackPath = item.route.path?.slice(0, 2) ?? [
            { lat: 35.1629, lng: 129.0532 },
            { lat: 35.157, lng: 129.059 },
          ];
          return {
            ...item,
            route: {
              ...item.route,
              segments: item.route.segments.map((segment) => {
                const needsPath =
                  (segment.mode === 'subway' && segment.hasElevator === true)
                  || (segment.mode === 'bus' && segment.isLowFloorBus === true);
                return needsPath
                  ? { ...segment, path: fallbackPath }
                  : segment;
              }),
            },
          };
        },
      );
      const withOverlay = recommendations.find(({ route }) =>
        route.segments.some(
          (segment) =>
            Boolean(segment.path?.length) &&
            ((segment.mode === 'subway' && segment.hasElevator === true) ||
              (segment.mode === 'bus' && segment.isLowFloorBus === true)),
        ),
      );
      useAppStore.setState({
        recommendations,
        selectedRouteId:
          withOverlay?.route.id ?? recommendations[0]?.route.id ?? null,
      });
    });

    const map = getByRole('region', { name: '지도' });
    const facility = getByRole('button', { name: '편의시설 오버레이' });
    expect(facility.getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(facility);
    expect(facility.getAttribute('aria-pressed')).toBe('true');
    expect(map.getAttribute('data-facilities-visible')).toBe('true');
    fireEvent.click(facility);
    expect(facility.getAttribute('aria-pressed')).toBe('false');
    expect(map.getAttribute('data-facilities-visible')).toBe('false');
  });

  it('시설 정보가 없으면 별도 안내를 표시한다', () => {
    const { getByRole } = render(<App />);
    act(() => {
      seedResults();
      const recommendations = useAppStore.getState().recommendations.map(
        (item) => ({
          ...item,
          route: {
            ...item.route,
            segments: item.route.segments.map((segment) => ({
              ...segment,
              hasElevator: undefined,
              isLowFloorBus: undefined,
            })),
          },
        }),
      );
      useAppStore.setState({ recommendations });
    });

    fireEvent.click(
      getByRole('button', { name: '편의시설 오버레이 자료 없음' }),
    );
    expect(
      document.querySelector('.map-first__fab-hint')?.textContent,
    ).toContain('표시 가능한 편의시설 정보가 없어요');
    expect(
      getByRole('region', { name: '지도' }).getAttribute(
        'data-facilities-visible',
      ),
    ).toBe('false');
  });

  it('상세 드로어가 열리면 음성 버튼이 사라지고 닫으면 다시 나타난다', () => {
    const { container, getByRole, queryByRole } = render(<App />);
    expect(getByRole('button', { name: '음성 챗봇' })).toBeTruthy();

    act(() => seedResults());
    expect(queryByRole('button', { name: '음성 챗봇' })).toBeNull();

    openSelectedRouteDetails(container);
    expect(queryByRole('button', { name: '음성 챗봇' })).toBeNull();
    fireEvent.keyDown(getByRole('dialog', { name: '경로 상세 정보' }), {
      key: 'Escape',
    });
    expect(queryByRole('button', { name: '음성 챗봇' })).toBeNull();

    fireEvent.click(
      getByRole('button', { name: '경로 결과 접기' }),
    );
    expect(getByRole('button', { name: '음성 챗봇' })).toBeTruthy();

    fireEvent.click(
      getByRole('button', { name: /프로필 선택, 현재/ }),
    );
    expect(queryByRole('button', { name: '음성 챗봇' })).toBeNull();
    fireEvent.keyDown(getByRole('dialog', { name: '이동 프로필 선택' }), {
      key: 'Escape',
    });
    expect(getByRole('button', { name: '음성 챗봇' })).toBeTruthy();
  });
});

describe('store 최신 요청 및 점수 계약', () => {
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
    const previousRecommendations =
      useAppStore.getState().recommendations;
    vi.spyOn(adapters.routes, 'recommend').mockImplementationOnce(
      () => previous.promise,
    );

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
      score: {
        ...item.score,
        finalScore: item.score.finalScore + 0.5,
      },
    }));
    useAppStore.setState({
      candidates: [],
      recommendations: [],
      selectedRouteId: null,
      loading: false,
    });
    const routes = vi
      .spyOn(adapters.routes, 'recommend')
      .mockImplementationOnce(() => previous.promise)
      .mockResolvedValueOnce(rainRecommendations);
    vi.spyOn(adapters.weather, 'getCurrent').mockResolvedValue(
      WEATHER_SCENARIOS.rain,
    );

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

  it('그늘 시각 변경은 경로 추천을 다시 호출하지 않고 기존 후보만 갱신한다', async () => {
    seedResults();
    const baseline = useAppStore.getState().recommendations;
    const refreshed = baseline.map((item) => ({
      ...item,
      route: {
        ...item.route,
        shade: {
          status: 'not_daylight' as const,
          evaluatedAt: '2026-07-24T02:00:00+09:00',
          source: 'test',
          dataQuality: 'demo' as const,
          shadowPolygons: [],
          pathSegments: [],
          calculationNote: '야간',
        },
      },
    }));
    const recommend = vi.spyOn(adapters.routes, 'recommend');
    const refreshShade = vi
      .spyOn(adapters.routes, 'refreshShade')
      .mockResolvedValue(refreshed);

    await useAppStore
      .getState()
      .setDepartureAt('2026-07-24T02:00:00+09:00');

    await waitFor(() => {
      expect(useAppStore.getState().recommendations).toEqual(refreshed);
    });
    expect(refreshShade).toHaveBeenCalledOnce();
    expect(refreshShade.mock.calls[0][3].departureAt).toBe(
      '2026-07-24T02:00:00+09:00',
    );
    expect(recommend).not.toHaveBeenCalled();
  });
});
