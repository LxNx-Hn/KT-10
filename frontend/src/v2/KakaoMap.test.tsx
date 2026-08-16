// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type {
  LatLng,
  Place,
  RouteCandidate,
  RouteSegment,
  ScoredRoute,
} from '@/types';
import KakaoMap, {
  KT_CLIMATE_SHELTER_MAX_VISIBLE_LEVEL,
  SHADOW_FILL,
  SHADOW_STROKE,
} from './KakaoMap';
import { ALTERNATIVE_ROUTE_COLOR } from './transportModeVisual';

const loaderMocks = vi.hoisted(() => ({
  hasKakaoKey: vi.fn(() => true),
  loadKakaoMaps: vi.fn(),
}));

vi.mock('@/map/kakaoLoader', () => loaderMocks);

type MockLatLngValue = {
  lat: number;
  lng: number;
  getLat: () => number;
  getLng: () => number;
};

type MockPolylineOptions = {
  path: MockLatLngValue[];
  strokeWeight: number;
  strokeColor: string;
  strokeOpacity: number;
  strokeStyle?: string;
  clickable?: boolean;
  zIndex?: number;
};

type MockPolygonOptions = {
  path: MockLatLngValue[];
  strokeWeight: number;
  strokeColor: string;
  strokeOpacity: number;
  fillColor: string;
  fillOpacity: number;
  zIndex?: number;
};

type MockOverlayOptions = {
  position: MockLatLngValue;
  content: HTMLElement;
  xAnchor?: number;
  yAnchor?: number;
  zIndex?: number;
};

class MockLatLng implements MockLatLngValue {
  constructor(
    public readonly lat: number,
    public readonly lng: number,
  ) {
    sdkRecords.latLngs.push(this);
  }

  getLat() {
    return this.lat;
  }

  getLng() {
    return this.lng;
  }
}

class MockLatLngBounds {
  readonly points: MockLatLngValue[] = [];

  extend(point: MockLatLngValue) {
    this.points.push(point);
  }
}

class MockMap {
  readonly boundsCalls: Array<{
    bounds: MockLatLngBounds;
    paddingTop?: number;
    paddingRight?: number;
    paddingBottom?: number;
    paddingLeft?: number;
  }> = [];

  readonly centerCalls: MockLatLngValue[] = [];
  readonly levelCalls: number[] = [];
  level: number;

  constructor(
    public readonly container: HTMLElement,
    public readonly options: {
      center: MockLatLngValue;
      level: number;
      draggable?: boolean;
      scrollwheel?: boolean;
    },
  ) {
    this.level = options.level;
    sdkRecords.maps.push(this);
  }

  setBounds(
    bounds: MockLatLngBounds,
    paddingTop?: number,
    paddingRight?: number,
    paddingBottom?: number,
    paddingLeft?: number,
  ) {
    this.boundsCalls.push({
      bounds,
      paddingTop,
      paddingRight,
      paddingBottom,
      paddingLeft,
    });
  }

  setCenter(point: MockLatLngValue) {
    this.centerCalls.push(point);
  }

  getLevel() {
    return this.level;
  }

  setLevel(level: number) {
    this.level = level;
    this.levelCalls.push(level);
    zoomChangedHandlers.get(this)?.();
  }

  relayout() {}

  setDraggable(_draggable: boolean) {}

  setZoomable(_zoomable: boolean) {}
}

class MockGraphic {
  map: MockMap | null = null;
  readonly mapCalls: Array<MockMap | null> = [];

  setMap(map: MockMap | null) {
    this.map = map;
    this.mapCalls.push(map);
  }
}

class MockPolyline extends MockGraphic {
  constructor(public readonly options: MockPolylineOptions) {
    super();
    sdkRecords.polylines.push(this);
  }
}

class MockPolygon extends MockGraphic {
  constructor(public readonly options: MockPolygonOptions) {
    super();
    sdkRecords.polygons.push(this);
  }
}

class MockCustomOverlay extends MockGraphic {
  constructor(public readonly options: MockOverlayOptions) {
    super();
    sdkRecords.overlays.push(this);
  }

  setPosition(position: MockLatLngValue) {
    this.options.position = position;
  }

  setZIndex(zIndex: number) {
    this.options.zIndex = zIndex;
  }
}

const sdkRecords = {
  maps: [] as MockMap[],
  polylines: [] as MockPolyline[],
  polygons: [] as MockPolygon[],
  overlays: [] as MockCustomOverlay[],
  latLngs: [] as MockLatLng[],
};

let eventHandlers = new WeakMap<object, () => void>();
let zoomChangedHandlers = new WeakMap<object, () => void>();
let viewportHeight = 640;

const mapsApi = {
  LatLng: MockLatLng,
  LatLngBounds: MockLatLngBounds,
  Map: MockMap,
  Polyline: MockPolyline,
  Polygon: MockPolygon,
  CustomOverlay: MockCustomOverlay,
  event: {
    addListener: vi.fn(
      (target: object, type: 'click' | 'zoom_changed', handler: () => void) => {
        if (type === 'click') eventHandlers.set(target, handler);
        if (type === 'zoom_changed') zoomChangedHandlers.set(target, handler);
      },
    ),
    removeListener: vi.fn(
      (target: object, type: 'click' | 'zoom_changed', handler: () => void) => {
        if (type === 'click' && eventHandlers.get(target) === handler) {
          eventHandlers.delete(target);
        }
        if (
          type === 'zoom_changed'
          && zoomChangedHandlers.get(target) === handler
        ) {
          zoomChangedHandlers.delete(target);
        }
      },
    ),
  },
};

const kakaoNamespace = { maps: mapsApi };

const ORIGIN: Place = {
  id: 'origin',
  name: '부산역',
  lat: 35.1151,
  lng: 129.0414,
};

const MIDPOINT: LatLng = { lat: 35.117, lng: 129.044 };

const DESTINATION: Place = {
  id: 'destination',
  name: '북구청',
  lat: 35.1972,
  lng: 128.9902,
};

function routeSegment(
  id: string,
  path: LatLng[],
  geometryQuality?: RouteSegment['geometryQuality'],
): RouteSegment {
  return {
    id,
    mode: 'walk',
    description: `${id} 보행`,
    durationMin: 5,
    path,
    geometryQuality,
  };
}

function scoredRoute(
  id: string,
  overrides: Partial<Omit<RouteCandidate, 'id'>> = {},
): ScoredRoute {
  return {
    route: {
      id,
      summary: `${id} 경로`,
      origin: ORIGIN.name,
      destination: DESTINATION.name,
      segments: [],
      totalDurationMin: 15,
      totalWalkM: 900,
      transferCount: 0,
      ...overrides,
    },
    score: {
      routeId: id,
      components: {},
      display: {},
      finalScore: 80,
      lowFloorStatus: 'none',
      reasons: [],
      cautions: [],
      voiceSummary: `${id} 안내`,
    },
  };
}

function activePolylines() {
  return sdkRecords.polylines.filter((line) => line.map !== null);
}

function activePolygons() {
  return sdkRecords.polygons.filter((polygon) => polygon.map !== null);
}

function activeOverlays() {
  return sdkRecords.overlays.filter((overlay) => overlay.map !== null);
}

async function waitUntilReady() {
  await waitFor(() => {
    expect(screen.queryByText('지도 불러오는 중…')).toBeNull();
    expect(sdkRecords.maps).toHaveLength(1);
  });
}

/** 시내 경로·주변시설을 볼 수 있는 가까운 축척으로 맞춘다. */
function zoomMapToShelterVisibleLevel(
  level = Math.min(5, KT_CLIMATE_SHELTER_MAX_VISIBLE_LEVEL),
) {
  const map = sdkRecords.maps[0];
  expect(map).toBeTruthy();
  map.setLevel(level);
}

function shelterOverlaysOnMap() {
  return activeOverlays().filter((overlay) =>
    overlay.options.content.classList.contains('map-first__kakao-shelter'),
  );
}

function shelterOverlayInstances() {
  return sdkRecords.overlays.filter((overlay) =>
    overlay.options.content.classList.contains('map-first__kakao-shelter'),
  );
}

beforeEach(() => {
  sdkRecords.maps.length = 0;
  sdkRecords.polylines.length = 0;
  sdkRecords.polygons.length = 0;
  sdkRecords.overlays.length = 0;
  sdkRecords.latLngs.length = 0;
  eventHandlers = new WeakMap<object, () => void>();
  zoomChangedHandlers = new WeakMap<object, () => void>();
  viewportHeight = 640;
  mapsApi.event.addListener.mockClear();
  mapsApi.event.removeListener.mockClear();
  loaderMocks.hasKakaoKey.mockReturnValue(true);
  loaderMocks.loadKakaoMaps.mockResolvedValue(kakaoNamespace);
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}

      unobserve() {}

      disconnect() {}
    },
  );
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockImplementation(
    () => viewportHeight,
  );
  vi.spyOn(globalThis, 'requestAnimationFrame').mockImplementation((callback) => {
    callback(0);
    return 1;
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('KakaoMap production overlays', () => {
  it('SDK 로드 실패를 안내하고 같은 화면에서 다시 시도할 수 있다', async () => {
    loaderMocks.loadKakaoMaps
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValueOnce(kakaoNamespace);

    render(
      <KakaoMap
        origin={null}
        destination={null}
        recommendations={[]}
        selectedRouteId={null}
        onSelectRoute={vi.fn()}
      />,
    );

    expect((await screen.findByRole('alert')).textContent).toContain(
      '지도를 불러오지 못했어요',
    );
    fireEvent.click(screen.getByRole('button', { name: '지도 다시 불러오기' }));

    await waitUntilReady();
    expect(loaderMocks.loadKakaoMaps).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('실제 출·도착점과 선택 경로의 전체선·구간선을 그리고 대안 경로 클릭을 전달한다', async () => {
    const onSelectRoute = vi.fn();
    const selected = scoredRoute('selected', {
      path: [ORIGIN, MIDPOINT, DESTINATION],
      geometryQuality: 'exact',
      segments: [
        routeSegment('selected-part', [ORIGIN, MIDPOINT], 'mixed'),
      ],
    });
    const alternative = scoredRoute('alternative', {
      path: [
        ORIGIN,
        { lat: 35.14, lng: 129.02 },
        DESTINATION,
      ],
      // 공급자가 geometryQuality를 주지 않은 경로는 exact로 승격하면 안 된다.
    });

    render(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[selected, alternative]}
        selectedRouteId="selected"
        onSelectRoute={onSelectRoute}
      />,
    );
    await waitUntilReady();

    const endpoints = activeOverlays();
    expect(endpoints).toHaveLength(2);
    expect(
      endpoints.map((overlay) => ({
        label: overlay.options.content.getAttribute('aria-label'),
        lat: overlay.options.position.getLat(),
        lng: overlay.options.position.getLng(),
      })),
    ).toEqual([
      { label: '출발 부산역', lat: ORIGIN.lat, lng: ORIGIN.lng },
      {
        label: '도착 북구청',
        lat: DESTINATION.lat,
        lng: DESTINATION.lng,
      },
    ]);

    const fullRouteLines = activePolylines().filter(
      (line) => line.options.path.length === 3
        && line.options.strokeColor !== ALTERNATIVE_ROUTE_COLOR,
    );
    // 이동수단별 본선: 전체 path 외곽선(white) + 구간 도보(차콜 점선)
    expect(fullRouteLines.map((line) => line.options.strokeColor)).toEqual([
      '#ffffff',
    ]);
    expect(fullRouteLines.map((line) => line.options.zIndex)).toEqual([4]);
    expect(
      fullRouteLines.every((line) => line.options.strokeStyle === 'solid'),
    ).toBe(true);
    const walkLine = activePolylines().find(
      (line) => line.options.strokeColor === '#475569',
    );
    expect(walkLine?.options.strokeStyle).toBe('shortdash');
    expect(walkLine?.options.path.length).toBe(2);
    expect(
      activePolylines().some((line) => line.options.strokeColor === '#16a34a'),
    ).toBe(false);

    const alternativeLine = activePolylines().find(
      (line) => line.options.clickable === true,
    );
    expect(alternativeLine?.options.strokeColor).toBe(ALTERNATIVE_ROUTE_COLOR);
    expect(alternativeLine?.options.strokeColor).not.toBe(SHADOW_STROKE);
    expect(alternativeLine?.options.strokeColor).not.toBe(SHADOW_FILL);
    expect(alternativeLine?.options.strokeOpacity).toBe(0.38);
    expect(alternativeLine?.options.strokeStyle).toBe('shortdash');
    expect(alternativeLine?.options.zIndex).toBe(2);

    const clickAlternative = alternativeLine
      ? eventHandlers.get(alternativeLine)
      : undefined;
    expect(clickAlternative).toBeTypeOf('function');
    clickAlternative?.();
    expect(onSelectRoute).toHaveBeenCalledOnce();
    expect(onSelectRoute).toHaveBeenCalledWith('alternative');
  });

  it('경사 토글이 꺼져 있으면 slopeSegments가 있어도 경사색을 쓰지 않는다', async () => {
    // 경사 parts는 slopePercent만으로 색·선스타일이 정해지므로, 토글이 꺼진
    // 상태에서 만들어지면 도보선이 등급색으로 칠해진다.
    const walkPath = [ORIGIN, MIDPOINT, DESTINATION];
    const selected = scoredRoute('slope-toggle-off', {
      path: walkPath,
      geometryQuality: 'exact',
      segments: [routeSegment('walk', walkPath, 'exact')],
      terrain: {
        status: 'estimated_90m',
        avgSlopePercent: 6,
        maxSlopePercent: 6,
        minSlopePercent: 6,
        source: 'Busan DEM 90m (QGIS precomputed)',
        resolutionM: 90,
        slopeSegments: [
          {
            start: ORIGIN,
            end: MIDPOINT,
            slopePercent: 6,
            distanceM: 90,
            path: [ORIGIN, MIDPOINT],
          },
          {
            start: MIDPOINT,
            end: DESTINATION,
            slopePercent: 6,
            distanceM: 90,
            path: [MIDPOINT, DESTINATION],
          },
        ],
      },
    });

    render(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[selected]}
        selectedRouteId="slope-toggle-off"
        onSelectRoute={vi.fn()}
        showShade={false}
        showSlope={false}
      />,
    );
    await waitUntilReady();

    // 경사 등급색은 하나도 쓰이지 않는다.
    const slopeRampColors = ['#2FAE6B', '#F7C948', '#F58A2A', '#E3362D'];
    expect(
      activePolylines().filter(
        (line) => slopeRampColors.includes(line.options.strokeColor),
      ),
    ).toHaveLength(0);

    // 도보선은 기본 차콜 점선으로 남고, 공급자 원본 정점을 그대로 쓴다.
    const walkLine = activePolylines().find(
      (line) => line.options.strokeColor === '#475569',
    );
    expect(walkLine).toBeDefined();
    expect(walkLine?.options.strokeStyle).toBe('shortdash');
    expect(
      walkLine?.options.path.map((point) => [point.lat, point.lng]),
    ).toEqual(walkPath.map((point) => [point.lat, point.lng]));
  });

  it('경사 토글을 켜면 같은 경로가 경사 등급색으로 바뀐다', async () => {
    const walkPath = [ORIGIN, MIDPOINT, DESTINATION];
    const route = (id: string) => scoredRoute(id, {
      path: walkPath,
      geometryQuality: 'exact',
      segments: [routeSegment('walk', walkPath, 'exact')],
      terrain: {
        status: 'estimated_90m',
        avgSlopePercent: 6,
        maxSlopePercent: 6,
        minSlopePercent: 6,
        source: 'Busan DEM 90m (QGIS precomputed)',
        resolutionM: 90,
        slopeSegments: [{
          start: ORIGIN,
          end: MIDPOINT,
          slopePercent: 6,
          distanceM: 90,
          path: [ORIGIN, MIDPOINT],
        }],
      },
    });

    const { rerender } = render(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[route('slope-toggle')]}
        selectedRouteId="slope-toggle"
        onSelectRoute={vi.fn()}
        showShade={false}
        showSlope={false}
      />,
    );
    await waitUntilReady();
    expect(
      activePolylines().some((line) => line.options.strokeColor === '#F58A2A'),
    ).toBe(false);

    rerender(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[route('slope-toggle')]}
        selectedRouteId="slope-toggle"
        onSelectRoute={vi.fn()}
        showShade={false}
        showSlope
      />,
    );
    await waitFor(() => {
      expect(
        activePolylines().some((line) => line.options.strokeColor === '#F58A2A'),
      ).toBe(true);
    });
    expect(
      activePolylines().find((line) => line.options.strokeColor === '#F58A2A')
        ?.options.strokeStyle,
    ).toBe('solid');
    // 켠 뒤에는 기본 도보색 선이 남지 않는다.
    expect(
      activePolylines().some((line) => line.options.strokeColor === '#475569'),
    ).toBe(false);
  });

  it('90m 지형 표본 사이 경사를 구간별 색상으로 표시한다', async () => {
    const selected = scoredRoute('slope-segments', {
      path: [ORIGIN, MIDPOINT, DESTINATION],
      geometryQuality: 'exact',
      segments: [
        routeSegment('walk', [ORIGIN, MIDPOINT, DESTINATION], 'exact'),
      ],
      terrain: {
        status: 'estimated_90m',
        avgSlopePercent: 5,
        maxSlopePercent: 12,
        minSlopePercent: 2,
        source: 'Busan DEM 90m (QGIS precomputed)',
        resolutionM: 90,
        slopeSegments: [
          {
            start: ORIGIN,
            end: MIDPOINT,
            slopePercent: 2,
            distanceM: 90,
          },
          {
            start: MIDPOINT,
            end: DESTINATION,
            slopePercent: 12,
            distanceM: 90,
          },
        ],
      },
    });

    render(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[selected]}
        selectedRouteId="slope-segments"
        onSelectRoute={vi.fn()}
      />,
    );
    await waitUntilReady();

    const coloredSegments = activePolylines().filter(
      (line) => ['#2FAE6B', '#E3362D'].includes(line.options.strokeColor),
    );
    expect(coloredSegments.map((line) => line.options.strokeColor)).toEqual([
      '#2FAE6B',
      '#E3362D',
    ]);
    expect(coloredSegments.every((line) => line.options.path.length === 2))
      .toBe(true);
    // 파란 선택 본선이 경사선 위를 덮지 않는다
    expect(
      activePolylines().some((line) => line.options.strokeColor === '#3182f6'),
    ).toBe(false);
    expect(coloredSegments.every((line) => line.options.zIndex === 6)).toBe(true);
    expect(
      coloredSegments.every((line) => line.options.strokeWeight >= 7
        && line.options.strokeWeight <= 9),
    ).toBe(true);
  });

  it('경사 구간 표시 경로가 있으면 표본 직선 대신 원본 보행 정점을 따라 그린다', async () => {
    // 90m 표본 사이에서 실제 보행로가 직각으로 꺾이는 상황.
    const cornerA: LatLng = { lat: 35.1151, lng: 129.044 };
    const cornerB: LatLng = { lat: 35.117, lng: 129.0414 };
    const walkPath = [ORIGIN, cornerA, MIDPOINT, cornerB, DESTINATION];
    const selected = scoredRoute('slope-segment-path', {
      path: walkPath,
      geometryQuality: 'exact',
      segments: [routeSegment('walk', walkPath, 'exact')],
      terrain: {
        status: 'estimated_90m',
        avgSlopePercent: 5,
        maxSlopePercent: 12,
        minSlopePercent: 2,
        source: 'Busan DEM 90m (QGIS precomputed)',
        resolutionM: 90,
        slopeSegments: [
          {
            start: ORIGIN,
            end: MIDPOINT,
            slopePercent: 2,
            distanceM: 90,
            path: [ORIGIN, cornerA, MIDPOINT],
          },
          {
            start: MIDPOINT,
            end: DESTINATION,
            slopePercent: 12,
            distanceM: 90,
            path: [MIDPOINT, cornerB, DESTINATION],
          },
        ],
      },
    });

    render(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[selected]}
        selectedRouteId="slope-segment-path"
        onSelectRoute={vi.fn()}
      />,
    );
    await waitUntilReady();

    const coloredSegments = activePolylines().filter(
      (line) => ['#2FAE6B', '#E3362D'].includes(line.options.strokeColor),
    );
    expect(coloredSegments.map((line) => line.options.strokeColor)).toEqual([
      '#2FAE6B',
      '#E3362D',
    ]);
    // 표본 두 점이 아니라 그 사이 코너 정점까지 그린다.
    expect(
      coloredSegments.map((line) => line.options.path.map(
        (point) => [point.lat, point.lng],
      )),
    ).toEqual([
      [
        [ORIGIN.lat, ORIGIN.lng],
        [cornerA.lat, cornerA.lng],
        [MIDPOINT.lat, MIDPOINT.lng],
      ],
      [
        [MIDPOINT.lat, MIDPOINT.lng],
        [cornerB.lat, cornerB.lng],
        [DESTINATION.lat, DESTINATION.lng],
      ],
    ]);
  });

  it.each([
    [2, '#2FAE6B'],
    [2.01, '#F7C948'],
    [5.01, '#F58A2A'],
    [8.01, '#E3362D'],
  ] as const)(
    '도보 slopePercent %s → 지도선 %s',
    async (slopePercent, color) => {
      const selected = scoredRoute(`slope-${slopePercent}`, {
        path: [ORIGIN, DESTINATION],
        geometryQuality: 'exact',
        segments: [routeSegment('walk', [ORIGIN, DESTINATION], 'exact')],
        terrain: {
          status: 'estimated_90m',
          avgSlopePercent: slopePercent,
          maxSlopePercent: slopePercent,
          minSlopePercent: slopePercent,
          source: 'test',
          resolutionM: 90,
          slopeSegments: [{
            start: ORIGIN,
            end: DESTINATION,
            slopePercent,
            distanceM: 120,
          }],
        },
      });

      const { unmount } = render(
        <KakaoMap
          origin={ORIGIN}
          destination={DESTINATION}
          recommendations={[selected]}
          selectedRouteId={selected.route.id}
          onSelectRoute={vi.fn()}
        />,
      );
      await waitUntilReady();

      const slopeLines = activePolylines().filter(
        (line) => line.options.strokeColor === color,
      );
      expect(slopeLines.length).toBeGreaterThanOrEqual(1);
      expect(
        activePolylines().some((line) => line.options.strokeColor === '#3182f6'),
      ).toBe(false);
      unmount();
      expect(activePolylines()).toHaveLength(0);
    },
  );

  it('버스·지하철은 이동수단 색을 유지하고 경사 도보선과 함께 그린다', async () => {
    const busEnd = MIDPOINT;
    const selected = scoredRoute('mixed-slope', {
      path: [ORIGIN, MIDPOINT, DESTINATION],
      geometryQuality: 'exact',
      segments: [
        {
          id: 'w1',
          mode: 'walk',
          description: '도보',
          durationMin: 3,
          path: [ORIGIN, MIDPOINT],
          geometryQuality: 'exact',
        },
        {
          id: 'b1',
          mode: 'bus',
          description: '버스',
          durationMin: 8,
          path: [MIDPOINT, DESTINATION],
          geometryQuality: 'exact',
        },
      ],
      terrain: {
        status: 'estimated_90m',
        avgSlopePercent: 3,
        maxSlopePercent: 3,
        minSlopePercent: 3,
        source: 'test',
        resolutionM: 90,
        slopeSegments: [{
          start: ORIGIN,
          end: busEnd,
          slopePercent: 3,
          distanceM: 90,
        }],
      },
    });

    render(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[selected]}
        selectedRouteId="mixed-slope"
        onSelectRoute={vi.fn()}
      />,
    );
    await waitUntilReady();

    expect(
      activePolylines().some((line) => line.options.strokeColor === '#F7C948'),
    ).toBe(true);
    expect(
      activePolylines().some((line) => line.options.strokeColor === '#3182f6'),
    ).toBe(true); // bus MODE_COLOR
    expect(
      activePolylines().filter((line) => line.options.strokeColor === '#3182f6')
        .every((line) => line.options.path.length === 2),
    ).toBe(true); // 버스 구간만 파랑 (전체 선택선 아님)
  });

  it('경사 OFF일 때 도보·버스·지하철 색/패턴이 카드 의미와 같고 그늘 초록과 겹치지 않는다', async () => {
    const selected = scoredRoute('mode-colors', {
      path: [ORIGIN, MIDPOINT, DESTINATION],
      geometryQuality: 'exact',
      segments: [
        {
          id: 'w1',
          mode: 'walk',
          description: '도보',
          durationMin: 3,
          path: [ORIGIN, MIDPOINT],
          geometryQuality: 'exact',
        },
        {
          id: 'b1',
          mode: 'bus',
          description: '버스',
          durationMin: 8,
          path: [MIDPOINT, { lat: 35.15, lng: 129.05 }],
          geometryQuality: 'exact',
          busRouteName: '1001',
        },
        {
          id: 's1',
          mode: 'subway',
          description: '부산1호선',
          durationMin: 10,
          path: [{ lat: 35.15, lng: 129.05 }, DESTINATION],
          geometryQuality: 'exact',
        },
      ],
    });

    render(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[selected]}
        selectedRouteId="mode-colors"
        onSelectRoute={vi.fn()}
        showShade={false}
        showSlope={false}
      />,
    );
    await waitUntilReady();

    const walk = activePolylines().find((line) => line.options.strokeColor === '#475569');
    const bus = activePolylines().find((line) => line.options.strokeColor === '#3182f6');
    const subway = activePolylines().find((line) => line.options.strokeColor === '#f06a00');
    expect(walk?.options.strokeStyle).toBe('shortdash');
    expect(bus?.options.strokeStyle).toBe('solid');
    expect(subway?.options.strokeStyle).toBe('solid');
    expect(
      activePolylines().some((line) => line.options.strokeColor === '#00b84a'),
    ).toBe(false);
    expect(
      activePolylines().some((line) => line.options.strokeColor === '#16a34a'),
    ).toBe(false);
    expect(
      activePolylines().some((line) => line.options.strokeColor === '#7c3aed'),
    ).toBe(false);
  });

  it('estimated 버스·지하철도 실선이고 예비 경로는 그늘보다 낮은 z-index다', async () => {
    const selected = scoredRoute('estimated-transit', {
      path: [ORIGIN, MIDPOINT, DESTINATION],
      geometryQuality: 'mixed',
      segments: [
        {
          id: 'w1',
          mode: 'walk',
          description: '도보',
          durationMin: 3,
          path: [ORIGIN, MIDPOINT],
          geometryQuality: 'exact',
        },
        {
          id: 'b1',
          mode: 'bus',
          description: '버스',
          durationMin: 8,
          path: [MIDPOINT, { lat: 35.15, lng: 129.05 }],
          geometryQuality: 'estimated',
          busRouteName: '1001',
        },
        {
          id: 's1',
          mode: 'subway',
          description: '부산2호선',
          durationMin: 10,
          path: [{ lat: 35.15, lng: 129.05 }, DESTINATION],
          geometryQuality: 'estimated',
        },
      ],
    });
    const alternative = scoredRoute('alt-estimated', {
      path: [ORIGIN, { lat: 35.14, lng: 129.02 }, DESTINATION],
      geometryQuality: 'estimated',
    });

    render(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[selected, alternative]}
        selectedRouteId="estimated-transit"
        onSelectRoute={vi.fn()}
        showShade={false}
        showSlope={false}
      />,
    );
    await waitUntilReady();

    const walk = activePolylines().find((line) => line.options.strokeColor === '#475569');
    const bus = activePolylines().find((line) => line.options.strokeColor === '#3182f6');
    const subway = activePolylines().find((line) => line.options.strokeColor === '#81bf48');
    const alternativeLine = activePolylines().find(
      (line) => line.options.clickable === true,
    );
    expect(walk?.options.strokeStyle).toBe('shortdash');
    expect(bus?.options.strokeStyle).toBe('solid');
    expect(subway?.options.strokeStyle).toBe('solid');
    expect(alternativeLine?.options.strokeColor).toBe(ALTERNATIVE_ROUTE_COLOR);
    expect(alternativeLine?.options.strokeColor).not.toBe(SHADOW_STROKE);
    expect(alternativeLine?.options.zIndex).toBe(2);
    expect(bus?.options.zIndex).toBeGreaterThan(alternativeLine?.options.zIndex ?? 0);
  });

  it('선택 경로 변경 시 이전 Polyline을 제거하고 새 경사선만 남긴다', async () => {
    const first = scoredRoute('first', {
      path: [ORIGIN, MIDPOINT],
      geometryQuality: 'exact',
      segments: [routeSegment('walk', [ORIGIN, MIDPOINT], 'exact')],
      terrain: {
        status: 'estimated_90m',
        avgSlopePercent: 2,
        maxSlopePercent: 2,
        minSlopePercent: 2,
        source: 'test',
        resolutionM: 90,
        slopeSegments: [{
          start: ORIGIN,
          end: MIDPOINT,
          slopePercent: 2,
          distanceM: 90,
        }],
      },
    });
    const second = scoredRoute('second', {
      path: [MIDPOINT, DESTINATION],
      geometryQuality: 'exact',
      segments: [routeSegment('walk', [MIDPOINT, DESTINATION], 'exact')],
      terrain: {
        status: 'estimated_90m',
        avgSlopePercent: 9,
        maxSlopePercent: 9,
        minSlopePercent: 9,
        source: 'test',
        resolutionM: 90,
        slopeSegments: [{
          start: MIDPOINT,
          end: DESTINATION,
          slopePercent: 9,
          distanceM: 90,
        }],
      },
    });

    const { rerender } = render(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[first, second]}
        selectedRouteId="first"
        onSelectRoute={vi.fn()}
      />,
    );
    await waitUntilReady();
    expect(
      activePolylines().some((line) => line.options.strokeColor === '#2FAE6B'),
    ).toBe(true);

    rerender(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[first, second]}
        selectedRouteId="second"
        onSelectRoute={vi.fn()}
      />,
    );
    await waitFor(() => {
      expect(
        activePolylines().some((line) => line.options.strokeColor === '#E3362D'),
      ).toBe(true);
    });
    expect(
      activePolylines().some((line) => line.options.strokeColor === '#2FAE6B'),
    ).toBe(false);
  });

  it('그늘 폴리곤과 90m 경사선을 동시에 표시하고 경사선을 위에 배치한다', async () => {
    const selected = scoredRoute('layer-order', {
      path: [ORIGIN, MIDPOINT, DESTINATION],
      geometryQuality: 'exact',
      segments: [
        routeSegment('walk', [ORIGIN, MIDPOINT, DESTINATION], 'exact'),
      ],
      terrain: {
        status: 'estimated_90m',
        avgSlopePercent: 12,
        maxSlopePercent: 12,
        minSlopePercent: 12,
        source: 'Busan DEM 90m (QGIS precomputed)',
        resolutionM: 90,
        slopeSegments: [{
          start: ORIGIN,
          end: MIDPOINT,
          slopePercent: 12,
          distanceM: 90,
        }],
      },
      shade: {
        status: 'estimated_public',
        evaluatedAt: '2026-07-26T14:00:00+09:00',
        shadeRatio: 0.5,
        source: 'VWorld LT_C_BLDGINFO WFS',
        dataQuality: 'public',
        shadowPolygons: [[ORIGIN, MIDPOINT, DESTINATION]],
        pathSegments: [
          { start: ORIGIN, end: MIDPOINT, shaded: true },
        ],
        calculationNote: '공공 건물 기반',
      },
    });

    render(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[selected]}
        selectedRouteId="layer-order"
        onSelectRoute={vi.fn()}
      />,
    );
    await waitUntilReady();

    expect(activePolygons()).toHaveLength(1);
    expect(
      activePolylines().filter(
        (line) => line.options.strokeColor === '#E3362D',
      ),
    ).toHaveLength(1);
    const shadeLine = activePolylines().find(
      (line) => line.options.strokeColor === '#00b84a',
    );
    const slopeLine = activePolylines().find(
      (line) => line.options.strokeColor === '#E3362D',
    );
    expect(shadeLine?.options.zIndex).toBe(3);
    expect(slopeLine?.options.zIndex).toBe(6);
  });

  it.each(['estimated_demo', 'estimated_public'] as const)(
    '%s 그늘만 건물 폴리곤과 녹색·주황 경로로 자동 표시하고 결과가 없으면 제거한다',
    async (status) => {
      const selected = scoredRoute('shade', {
        path: [ORIGIN, MIDPOINT, DESTINATION],
        geometryQuality: 'exact',
        segments: [],
        shade: {
          status,
          evaluatedAt: '2026-07-24T15:00:00+09:00',
          shadeRatio: 0.5,
          source: '검증용 건물 데이터',
          dataQuality: status === 'estimated_demo' ? 'demo' : 'public',
          shadowPolygons: [[
            { lat: 35.116, lng: 129.042 },
            { lat: 35.116, lng: 129.043 },
            { lat: 35.117, lng: 129.043 },
          ]],
          pathSegments: [
            { start: ORIGIN, end: MIDPOINT, shaded: true },
            { start: MIDPOINT, end: DESTINATION, shaded: false },
          ],
          calculationNote: '테스트',
        },
      });

      const view = render(
        <KakaoMap
          origin={ORIGIN}
          destination={DESTINATION}
          recommendations={[selected]}
          selectedRouteId="shade"
          onSelectRoute={vi.fn()}
        />,
      );
      await waitUntilReady();

      expect(activePolygons()).toHaveLength(1);
      expect(activePolygons()[0]?.options.zIndex).toBe(1);
      expect(activePolygons()[0]?.options.fillColor).toBe('#8290a8');

      const shadeLines = activePolylines().filter((line) =>
        ['#00b84a', '#ff5a1f'].includes(line.options.strokeColor),
      );
      expect(shadeLines.map((line) => line.options.strokeColor)).toEqual([
        '#00b84a',
        '#ff5a1f',
      ]);
      expect(
        shadeLines.every(
          (line) =>
            line.options.zIndex === 3
            && line.options.strokeStyle === 'solid',
        ),
      ).toBe(true);
      const selectedBaseZ = Math.max(
        ...activePolylines()
          .filter((line) =>
            ['#ffffff', '#3182f6'].includes(line.options.strokeColor),
          )
          .map((line) => line.options.zIndex ?? 0),
      );
      expect(Math.max(...shadeLines.map((line) => line.options.zIndex ?? 0)))
        .toBeLessThan(selectedBaseZ);

      // shade 결과가 없어지면 토글 없이 shade layer만 조용히 제거된다.
      const withoutShade = {
        ...selected,
        route: { ...selected.route, shade: undefined },
      };
      view.rerender(
        <KakaoMap
          origin={ORIGIN}
          destination={DESTINATION}
          recommendations={[withoutShade]}
          selectedRouteId="shade"
          onSelectRoute={vi.fn()}
        />,
      );

      await waitFor(() => {
        expect(activePolygons()).toHaveLength(0);
        expect(
          activePolylines().filter((line) =>
            ['#00b84a', '#ff5a1f'].includes(line.options.strokeColor),
          ),
        ).toHaveLength(0);
      });
    },
  );

  it('showShade=false이면 그늘 geometry가 있어도 시각화만 숨긴다', async () => {
    const selected = scoredRoute('shade-off', {
      path: [ORIGIN, MIDPOINT, DESTINATION],
      geometryQuality: 'exact',
      shade: {
        status: 'estimated_demo',
        evaluatedAt: '2026-07-23T14:00:00+09:00',
        shadeRatio: 0.5,
        source: 'test',
        dataQuality: 'demo',
        shadowPolygons: [[ORIGIN, MIDPOINT, DESTINATION]],
        pathSegments: [
          { start: ORIGIN, end: MIDPOINT, shaded: true },
          { start: MIDPOINT, end: DESTINATION, shaded: false },
        ],
        calculationNote: 'test',
      },
    });
    const scoreBefore = selected.score.finalScore;

    const view = render(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[selected]}
        selectedRouteId="shade-off"
        onSelectRoute={vi.fn()}
        showShade
      />,
    );
    await waitUntilReady();
    expect(activePolygons().length).toBeGreaterThan(0);

    view.rerender(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[selected]}
        selectedRouteId="shade-off"
        onSelectRoute={vi.fn()}
        showShade={false}
      />,
    );

    await waitFor(() => {
      expect(activePolygons()).toHaveLength(0);
      expect(
        activePolylines().filter((line) =>
          ['#00b84a', '#ff5a1f'].includes(line.options.strokeColor),
        ),
      ).toHaveLength(0);
    });
    expect(selected.score.finalScore).toBe(scoreBefore);
  });

  it('확인된 승강기와 저상버스만 편의시설 레이어에 표시하고 토글을 끄면 제거한다', async () => {
    const selected = scoredRoute('facilities', {
      path: [ORIGIN, MIDPOINT, DESTINATION],
      geometryQuality: 'exact',
      segments: [
        {
          ...routeSegment('subway', [ORIGIN, MIDPOINT], 'exact'),
          mode: 'subway',
          stationName: '부산역',
          hasElevator: true,
        },
        {
          ...routeSegment('bus', [MIDPOINT, DESTINATION], 'exact'),
          mode: 'bus',
          busRouteName: '1001번',
          isLowFloorBus: true,
        },
        {
          ...routeSegment('unknown', [ORIGIN, DESTINATION], 'exact'),
          mode: 'subway',
          stationName: '확인 전 역',
        },
      ],
    });

    const view = render(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[selected]}
        selectedRouteId="facilities"
        onSelectRoute={vi.fn()}
        showFacilities
        climateShelterGroups={[]}
      />,
    );
    await waitUntilReady();

    expect(
      activeOverlays()
        .map((overlay) => overlay.options.content.getAttribute('aria-label'))
        .filter((label) => label?.startsWith('승강기') || label?.startsWith('저상버스')),
    ).toEqual(['승강기 부산역', '저상버스 1001번']);

    const elevator = activeOverlays().find((overlay) =>
      overlay.options.content.classList.contains('map-first__kakao-facility--elevator'),
    );
    const bus = activeOverlays().find((overlay) =>
      overlay.options.content.classList.contains('map-first__kakao-facility--bus'),
    );
    expect(elevator).toBeTruthy();
    expect(bus).toBeTruthy();
    expect(elevator?.options.content.textContent).not.toContain('↕');
    expect(
      elevator?.options.content.querySelector('.map-first__kakao-facility-pictogram'),
    ).toBeTruthy();
    expect(
      bus?.options.content.querySelector('.map-first__kakao-facility-icon')?.textContent,
    ).toBe('저');

    view.rerender(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[selected]}
        selectedRouteId="facilities"
        onSelectRoute={vi.fn()}
        showFacilities={false}
        climateShelterGroups={[]}
      />,
    );

    await waitFor(() => {
      expect(
        activeOverlays().filter((overlay) =>
          overlay.options.content.classList.contains('map-first__kakao-facility'),
        ),
      ).toHaveLength(0);
    });
  });

  it('편의시설 ON이면 KT 기후쉼터 marker를 그리고 OFF면 제거하며 fitBounds에는 넣지 않는다', async () => {
    const selected = scoredRoute('shelters', {
      path: [ORIGIN, MIDPOINT, DESTINATION],
      geometryQuality: 'exact',
      segments: [routeSegment('walk', [ORIGIN, DESTINATION], 'exact')],
    });
    const groups = [
      {
        key: 'g1',
        lat: 35.2,
        lng: 129.1,
        shelters: [{
          id: '1',
          name: 'KT 테스트점',
          address: '연제구 시험로 1',
          lat: 35.2,
          lng: 129.1,
        }],
      },
      {
        key: 'g2',
        lat: 35.2098761,
        lng: 129.0064230,
        shelters: [
          {
            id: '2',
            name: 'KT 씨엘 젊음의거리점',
            address: '북구 A',
            lat: 35.2098761,
            lng: 129.0064230,
          },
          {
            id: '3',
            name: 'KT (주)엘에스컴퍼니 덕천역점',
            address: '북구 B',
            lat: 35.2098761,
            lng: 129.0064230,
          },
        ],
      },
    ];

    const view = render(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[selected]}
        selectedRouteId="shelters"
        onSelectRoute={vi.fn()}
        showFacilities
        climateShelterGroups={groups}
      />,
    );
    await waitUntilReady();

    zoomMapToShelterVisibleLevel();
    const shelterOverlays = shelterOverlaysOnMap();
    expect(shelterOverlays).toHaveLength(2);
    expect(
      shelterOverlays.map((overlay) =>
        overlay.options.content
          .querySelector('.map-first__kakao-shelter-marker')
          ?.getAttribute('aria-label'),
      ),
    ).toEqual([
      'KT 기후쉼터 KT 테스트점',
      'KT 기후쉼터 2곳: KT 씨엘 젊음의거리점, KT (주)엘에스컴퍼니 덕천역점',
    ]);

    const map = sdkRecords.maps[0];
    const lastBoundsCall = map.boundsCalls[map.boundsCalls.length - 1];
    expect(lastBoundsCall).toBeTruthy();
    const boundLats = lastBoundsCall.bounds.points.map(
      (point: { lat: number }) => point.lat,
    );
    expect(boundLats).not.toContain(35.2);
    expect(boundLats).not.toContain(35.2098761);

    view.rerender(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[selected]}
        selectedRouteId="shelters"
        onSelectRoute={vi.fn()}
        showFacilities={false}
        climateShelterGroups={groups}
      />,
    );
    await waitFor(() => {
      expect(shelterOverlaysOnMap()).toHaveLength(0);
    });
  });

  it('가까운 zoom에서만 KT 기후쉼터를 표시하고 넓게 zoom-out하면 setMap으로 숨긴다', async () => {
    const selected = scoredRoute('shelter-zoom', {
      path: [ORIGIN, MIDPOINT, DESTINATION],
      geometryQuality: 'exact',
      segments: [
        {
          ...routeSegment('subway', [ORIGIN, MIDPOINT], 'exact'),
          mode: 'subway',
          stationName: '부산역',
          hasElevator: true,
        },
      ],
    });
    const groups = [
      {
        key: 'g1',
        lat: 35.2,
        lng: 129.1,
        shelters: [{
          id: '1',
          name: 'KT 테스트점',
          address: '연제구 시험로 1',
          lat: 35.2,
          lng: 129.1,
        }],
      },
    ];

    const view = render(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[selected]}
        selectedRouteId="shelter-zoom"
        onSelectRoute={vi.fn()}
        showFacilities
        climateShelterGroups={groups}
      />,
    );
    await waitUntilReady();

    const map = sdkRecords.maps[0];
    const boundsBeforeZoom = map.boundsCalls.length;
    expect(map.getLevel()).toBeGreaterThan(KT_CLIMATE_SHELTER_MAX_VISIBLE_LEVEL);
    expect(shelterOverlaysOnMap()).toHaveLength(0);
    expect(shelterOverlayInstances().length).toBeGreaterThanOrEqual(1);
    expect(
      activeOverlays().some((overlay) =>
        overlay.options.content.getAttribute('aria-label')?.startsWith('승강기'),
      ),
    ).toBe(true);

    const instanceCountAtFar = shelterOverlayInstances().length;
    zoomMapToShelterVisibleLevel();
    expect(shelterOverlaysOnMap()).toHaveLength(1);
    expect(shelterOverlayInstances()).toHaveLength(instanceCountAtFar);
    const shelter = shelterOverlaysOnMap()[0];
    const mapCallsAfterShow = shelter.mapCalls.length;

    map.setLevel(KT_CLIMATE_SHELTER_MAX_VISIBLE_LEVEL + 1);
    expect(shelterOverlaysOnMap()).toHaveLength(0);
    expect(shelterOverlayInstances()).toHaveLength(instanceCountAtFar);
    expect(shelter.map).toBeNull();
    expect(shelter.mapCalls.length).toBeGreaterThan(mapCallsAfterShow);
    expect(
      activeOverlays().some((overlay) =>
        overlay.options.content.getAttribute('aria-label')?.startsWith('승강기'),
      ),
    ).toBe(true);

    zoomMapToShelterVisibleLevel();
    expect(shelterOverlaysOnMap()).toHaveLength(1);
    expect(shelterOverlayInstances()).toHaveLength(instanceCountAtFar);
    expect(shelter.map).toBe(map);
    expect(map.boundsCalls.length).toBe(boundsBeforeZoom);

    view.rerender(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[selected]}
        selectedRouteId="shelter-zoom"
        onSelectRoute={vi.fn()}
        showFacilities={false}
        climateShelterGroups={groups}
      />,
    );
    await waitFor(() => {
      expect(shelterOverlaysOnMap()).toHaveLength(0);
    });
    expect(
      activeOverlays().some((overlay) =>
        overlay.options.content.classList.contains('map-first__kakao-shelter'),
      ),
    ).toBe(false);
    expect(map.boundsCalls.length).toBe(boundsBeforeZoom);
  });

  it('쉼터 기본/선택 marker 클래스와 detail bubble z-index를 분리하고 열리면 overlay 우선순위를 올린다', async () => {
    const selected = scoredRoute('shelter-visual', {
      path: [ORIGIN, MIDPOINT, DESTINATION],
      geometryQuality: 'exact',
      segments: [routeSegment('walk', [ORIGIN, DESTINATION], 'exact')],
    });
    const groups = [
      {
        key: 'g1',
        lat: 35.2,
        lng: 129.1,
        shelters: [{
          id: '1',
          name: 'KT 테스트점',
          address: '연제구 시험로 1',
          lat: 35.2,
          lng: 129.1,
        }],
      },
      {
        key: 'g2',
        lat: 35.21,
        lng: 129.11,
        shelters: [{
          id: '2',
          name: 'KT 다른점',
          address: '북구 시험로 2',
          lat: 35.21,
          lng: 129.11,
        }],
      },
    ];

    render(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[selected]}
        selectedRouteId="shelter-visual"
        onSelectRoute={vi.fn()}
        showFacilities
        climateShelterGroups={groups}
      />,
    );
    await waitUntilReady();
    zoomMapToShelterVisibleLevel();

    const shelterOverlays = shelterOverlaysOnMap();
    expect(shelterOverlays).toHaveLength(2);
    expect(shelterOverlays.every((overlay) => overlay.options.zIndex === 5)).toBe(true);

    const first = shelterOverlays[0];
    const second = shelterOverlays[1];
    const firstRoot = first.options.content;
    const firstMarker = firstRoot.querySelector('.map-first__kakao-shelter-marker');
    const firstBubble = firstRoot.querySelector('.map-first__kakao-shelter-bubble');
    const secondMarker = second.options.content.querySelector(
      '.map-first__kakao-shelter-marker',
    );

    expect(firstMarker?.textContent).toBe('쉼');
    expect(firstRoot.classList.contains('map-first__kakao-shelter--open')).toBe(false);
    expect(firstBubble).toBeTruthy();
    expect(firstBubble).toHaveProperty('hidden', true);

    fireEvent.click(firstMarker!);
    expect(firstRoot.classList.contains('map-first__kakao-shelter--open')).toBe(true);
    expect(firstMarker?.getAttribute('aria-expanded')).toBe('true');
    expect(firstBubble).toHaveProperty('hidden', false);
    expect(first.options.zIndex).toBe(12);
    expect(second.options.zIndex).toBe(5);
    expect(first.options.zIndex!).toBeGreaterThan(second.options.zIndex!);

    fireEvent.click(secondMarker!);
    expect(firstRoot.classList.contains('map-first__kakao-shelter--open')).toBe(false);
    expect(first.options.zIndex).toBe(5);
    expect(second.options.content.classList.contains('map-first__kakao-shelter--open')).toBe(
      true,
    );
    expect(second.options.zIndex).toBe(12);
  });

  it('잘못된 좌표를 버리고 품질 미확인 구간을 임의 좌표나 실선으로 보정하지 않는다', async () => {
    const validUnknownSegment = [
      { lat: 35.12, lng: 129.04 },
      { lat: 35.121, lng: 129.041 },
    ];
    const selected = scoredRoute('unknown', {
      path: [
        validUnknownSegment[0],
        { lat: Number.NaN, lng: 129.05 },
      ],
      segments: [routeSegment('unknown-part', validUnknownSegment)],
    });
    const invalidOrigin: Place = { ...ORIGIN, lat: 999 };
    const invalidDestination: Place = {
      ...DESTINATION,
      lng: Number.POSITIVE_INFINITY,
    };

    render(
      <KakaoMap
        origin={invalidOrigin}
        destination={invalidDestination}
        recommendations={[selected]}
        selectedRouteId="unknown"
        onSelectRoute={vi.fn()}
      />,
    );
    await waitUntilReady();

    expect(activeOverlays()).toHaveLength(0);
    expect(activePolylines()).toHaveLength(2);
    expect(
      activePolylines().every(
        (line) => line.options.strokeStyle === 'shortdash',
      ),
    ).toBe(true);
    expect(
      activePolylines().map((line) =>
        line.options.path.map((point) => [point.getLat(), point.getLng()]),
      ),
    ).toEqual([
      validUnknownSegment.map((point) => [point.lat, point.lng]),
      validUnknownSegment.map((point) => [point.lat, point.lng]),
    ]);
    expect(
      sdkRecords.latLngs.every(
        (point) =>
          Number.isFinite(point.getLat())
          && Number.isFinite(point.getLng())
          && Math.abs(point.getLat()) <= 90
          && Math.abs(point.getLng()) <= 180,
      ),
    ).toBe(true);
    expect(
      sdkRecords.latLngs.some(
        (point) => point.getLat() === 0 && point.getLng() === 0,
      ),
    ).toBe(false);
  });

  it('작은 지도에서도 동적 bounds 여백 합을 제한해 실제 경로 표시 영역을 남긴다', async () => {
    viewportHeight = 180;
    const selected = scoredRoute('compact', {
      path: [ORIGIN, DESTINATION],
      geometryQuality: 'exact',
    });

    render(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[selected]}
        selectedRouteId="compact"
        onSelectRoute={vi.fn()}
      />,
    );
    await waitUntilReady();

    const map = sdkRecords.maps[0];
    const boundsCall = map?.boundsCalls[map.boundsCalls.length - 1];
    expect(boundsCall).toBeDefined();
    const top = boundsCall?.paddingTop ?? 0;
    const bottom = boundsCall?.paddingBottom ?? 0;
    expect(top).toBeGreaterThanOrEqual(24);
    expect(bottom).toBeGreaterThanOrEqual(32);
    expect(top + bottom).toBeLessThanOrEqual(80);
    expect(viewportHeight - top - bottom).toBeGreaterThanOrEqual(100);
    expect(boundsCall?.paddingRight).toBe(24);
    expect(boundsCall?.paddingLeft).toBe(24);
    expect(boundsCall?.bounds.points.length).toBeGreaterThanOrEqual(2);
  });

  it('상단 칩·하단 시트가 가리는 높이를 padding에 반영하고 OD를 bounds에 포함한다', async () => {
    viewportHeight = 640;
    const selected = scoredRoute('padded', {
      path: [MIDPOINT],
      geometryQuality: 'exact',
    });

    const mapRect = {
      top: 0,
      bottom: 640,
      left: 0,
      right: 390,
      width: 390,
      height: 640,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect;
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(
      function mockRect(this: HTMLElement) {
        if (this.classList.contains('map-first__kakao-canvas')) {
          return mapRect;
        }
        if (this.classList.contains('map-first__chip-row')) {
          return {
            top: 80,
            bottom: 140,
            left: 12,
            right: 378,
            width: 366,
            height: 60,
            x: 12,
            y: 80,
            toJSON: () => ({}),
          } as DOMRect;
        }
        if (this.classList.contains('map-first__sheet')) {
          return {
            top: 400,
            bottom: 640,
            left: 0,
            right: 390,
            width: 390,
            height: 240,
            x: 0,
            y: 400,
            toJSON: () => ({}),
          } as DOMRect;
        }
        return {
          top: 0,
          bottom: 0,
          left: 0,
          right: 0,
          width: 0,
          height: 0,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        } as DOMRect;
      },
    );
    vi.spyOn(window, 'getComputedStyle').mockImplementation(
      () =>
        ({
          display: 'block',
          visibility: 'visible',
          opacity: '1',
        }) as CSSStyleDeclaration,
    );

    const topHost = document.createElement('div');
    topHost.className = 'map-first__top';
    const chipRow = document.createElement('div');
    chipRow.className = 'map-first__chip-row';
    topHost.append(chipRow);
    const sheet = document.createElement('div');
    sheet.className = 'map-first__sheet';
    document.body.append(topHost, sheet);

    render(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[selected]}
        selectedRouteId="padded"
        onSelectRoute={vi.fn()}
      />,
    );
    await waitUntilReady();

    const map = sdkRecords.maps[0];
    const boundsCall = map?.boundsCalls[map.boundsCalls.length - 1];
    expect(boundsCall?.paddingTop).toBe(164); // 140 - 0 + 24
    expect(boundsCall?.paddingBottom).toBe(272); // 640 - 400 + 32
    const lats = boundsCall?.bounds.points.map((point) => point.getLat()) ?? [];
    expect(lats).toContain(ORIGIN.lat);
    expect(lats).toContain(DESTINATION.lat);

    topHost.remove();
    sheet.remove();
  });

  it('같은 선택 경로·geometry·레이아웃이면 자동 fit을 중복 실행하지 않는다', async () => {
    const selected = scoredRoute('stable', {
      path: [ORIGIN, MIDPOINT, DESTINATION],
      geometryQuality: 'exact',
    });
    const onSelectRoute = vi.fn();
    const { rerender } = render(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[selected]}
        selectedRouteId="stable"
        onSelectRoute={onSelectRoute}
        layoutFitKey="compact|sheet-expanded|none"
        showFacilities={false}
      />,
    );
    await waitUntilReady();
    const map = sdkRecords.maps[0];
    const firstCount = map.boundsCalls.length;
    expect(firstCount).toBeGreaterThanOrEqual(1);

    rerender(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[selected]}
        selectedRouteId="stable"
        onSelectRoute={vi.fn()}
        layoutFitKey="compact|sheet-expanded|none"
        showFacilities={true}
      />,
    );
    await waitFor(() => {
      expect(sdkRecords.maps).toHaveLength(1);
    });
    expect(map.boundsCalls.length).toBe(firstCount);
  });

  it('layoutFitKey medium→expanded는 서로 다른 상태로 취급하고 전환 후 bottom padding이 증가한다', async () => {
    viewportHeight = 640;
    const selected = scoredRoute('snap-pad', {
      path: [ORIGIN, MIDPOINT, DESTINATION],
      geometryQuality: 'exact',
    });

    const mapRect = {
      top: 0,
      bottom: 640,
      left: 0,
      right: 390,
      width: 390,
      height: 640,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect;

    let sheetTop = 352; // medium ≈ 45% visible map → bottom covered 288
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(
      function mockRect(this: HTMLElement) {
        if (this.classList.contains('map-first__kakao-canvas')) {
          return mapRect;
        }
        if (this.classList.contains('map-first__sheet')) {
          return {
            top: sheetTop,
            bottom: 640,
            left: 0,
            right: 390,
            width: 390,
            height: 640 - sheetTop,
            x: 0,
            y: sheetTop,
            toJSON: () => ({}),
          } as DOMRect;
        }
        return {
          top: 0,
          bottom: 0,
          left: 0,
          right: 0,
          width: 0,
          height: 0,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        } as DOMRect;
      },
    );
    vi.spyOn(window, 'getComputedStyle').mockImplementation(
      () =>
        ({
          display: 'block',
          visibility: 'visible',
          opacity: '1',
        }) as CSSStyleDeclaration,
    );

    const sheet = document.createElement('div');
    sheet.className = 'map-first__sheet';
    document.body.append(sheet);

    const { rerender } = render(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[selected]}
        selectedRouteId="snap-pad"
        onSelectRoute={vi.fn()}
        layoutFitKey="compact|sheet-medium|none"
      />,
    );
    await waitUntilReady();

    const map = sdkRecords.maps[0];
    const mediumCount = map.boundsCalls.length;
    expect(mediumCount).toBeGreaterThanOrEqual(1);
    const mediumPad =
      map.boundsCalls[mediumCount - 1]?.paddingBottom ?? 0;
    expect(mediumPad).toBe(320); // 640 - 352 + 32

    // transition 중간(드래그/중간 프레임)과 동일한 geometry·key로는 재호출 없음
    rerender(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[selected]}
        selectedRouteId="snap-pad"
        onSelectRoute={vi.fn()}
        layoutFitKey="compact|sheet-medium|none"
      />,
    );
    expect(map.boundsCalls.length).toBe(mediumCount);

    sheetTop = 64; // expanded ≈ 90% sheet
    rerender(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[selected]}
        selectedRouteId="snap-pad"
        onSelectRoute={vi.fn()}
        layoutFitKey="compact|sheet-expanded|none"
      />,
    );
    await waitFor(() => {
      expect(map.boundsCalls.length).toBeGreaterThan(mediumCount);
    });
    const expandedPad =
      map.boundsCalls[map.boundsCalls.length - 1]?.paddingBottom ?? 0;
    // raw bottom would be 608, but visible-strip clamp scales top+bottom.
    expect(expandedPad).toBeGreaterThan(mediumPad);
    expect(expandedPad).toBe(493);

    const afterExpanded = map.boundsCalls.length;
    rerender(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[selected]}
        selectedRouteId="snap-pad"
        onSelectRoute={vi.fn()}
        layoutFitKey="compact|sheet-expanded|none"
      />,
    );
    expect(map.boundsCalls.length).toBe(afterExpanded);

    sheet.remove();
  });

  it('선택 경로 변경 시 새 geometry로 setBounds를 다시 수행한다', async () => {
    const first = scoredRoute('first', {
      path: [ORIGIN, MIDPOINT],
      geometryQuality: 'exact',
    });
    const second = scoredRoute('second', {
      path: [ORIGIN, DESTINATION],
      geometryQuality: 'exact',
    });
    const { rerender } = render(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[first, second]}
        selectedRouteId="first"
        onSelectRoute={vi.fn()}
        layoutFitKey="compact|sheet-medium|none"
      />,
    );
    await waitUntilReady();
    const map = sdkRecords.maps[0];
    const before = map.boundsCalls.length;
    const firstLats =
      map.boundsCalls[before - 1]?.bounds.points.map((p) => p.getLat()) ?? [];
    expect(firstLats).toContain(MIDPOINT.lat);

    rerender(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[first, second]}
        selectedRouteId="second"
        onSelectRoute={vi.fn()}
        layoutFitKey="compact|sheet-medium|none"
      />,
    );
    await waitFor(() => {
      expect(map.boundsCalls.length).toBeGreaterThan(before);
    });
    const last =
      map.boundsCalls[map.boundsCalls.length - 1]?.bounds.points.map((p) =>
        p.getLat(),
      ) ?? [];
    expect(last).toContain(DESTINATION.lat);
  });
});
