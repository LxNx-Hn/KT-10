// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type {
  LatLng,
  Place,
  RouteCandidate,
  RouteSegment,
  ScoredRoute,
} from '@/types';
import KakaoMap from './KakaoMap';

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

  constructor(
    public readonly container: HTMLElement,
    public readonly options: {
      center: MockLatLngValue;
      level: number;
      draggable?: boolean;
      scrollwheel?: boolean;
    },
  ) {
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

  setLevel(level: number) {
    this.levelCalls.push(level);
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
}

const sdkRecords = {
  maps: [] as MockMap[],
  polylines: [] as MockPolyline[],
  polygons: [] as MockPolygon[],
  overlays: [] as MockCustomOverlay[],
  latLngs: [] as MockLatLng[],
};

let eventHandlers = new WeakMap<object, () => void>();
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
      (target: object, type: 'click', handler: () => void) => {
        if (type === 'click') eventHandlers.set(target, handler);
      },
    ),
    removeListener: vi.fn(
      (target: object, type: 'click', handler: () => void) => {
        if (type === 'click' && eventHandlers.get(target) === handler) {
          eventHandlers.delete(target);
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

beforeEach(() => {
  sdkRecords.maps.length = 0;
  sdkRecords.polylines.length = 0;
  sdkRecords.polygons.length = 0;
  sdkRecords.overlays.length = 0;
  sdkRecords.latLngs.length = 0;
  eventHandlers = new WeakMap<object, () => void>();
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
        && line.options.strokeColor !== '#64748b',
    );
    // slopeSegments 없음: 흰 외곽선 + 파란 선택 본선만 (도보 구간 녹색 오버레이 없음)
    expect(fullRouteLines).toHaveLength(2);
    expect(fullRouteLines.map((line) => line.options.strokeColor)).toEqual([
      '#ffffff',
      '#3182f6',
    ]);
    expect(fullRouteLines.map((line) => line.options.zIndex)).toEqual([4, 5]);
    expect(
      fullRouteLines.every((line) => line.options.strokeStyle === 'solid'),
    ).toBe(true);
    expect(
      activePolylines().some((line) => line.options.strokeColor === '#16a34a'),
    ).toBe(false);

    const alternativeLine = activePolylines().find(
      (line) => line.options.clickable === true,
    );
    expect(alternativeLine?.options.strokeColor).toBe('#64748b');
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
      />,
    );
    await waitUntilReady();

    expect(
      activeOverlays()
        .map((overlay) => overlay.options.content.getAttribute('aria-label'))
        .filter((label) => label?.startsWith('승강기') || label?.startsWith('저상버스')),
    ).toEqual(['승강기 부산역', '저상버스 1001번']);

    view.rerender(
      <KakaoMap
        origin={ORIGIN}
        destination={DESTINATION}
        recommendations={[selected]}
        selectedRouteId="facilities"
        onSelectRoute={vi.fn()}
        showFacilities={false}
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
});
