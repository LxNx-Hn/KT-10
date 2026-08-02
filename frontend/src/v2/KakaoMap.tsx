import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from 'react';
import { DISTRICT } from '@/config/district';
import { hasKakaoKey, loadKakaoMaps } from '@/map/kakaoLoader';
import type {
  LatLng,
  Place,
  RouteCandidate,
  ScoredRoute,
  SegmentMode,
} from '@/types';

export type LngLatTuple = [number, number];

/** Imperative map API used by the map-first current-location control. */
export type KakaoMapHandle = {
  flyToUserLocation: (coords: LngLatTuple) => void;
  clearUserLocation: () => void;
};

export type KakaoMapProps = {
  origin: Place | null;
  destination: Place | null;
  recommendations: ScoredRoute[];
  selectedRouteId: string | null;
  onSelectRoute: (routeId: string) => void;
  showFacilities?: boolean;
  /** Overlay layout signature (search panel / sheet / drawer) for visible-area fits. */
  layoutFitKey?: string;
};

type GeometryQuality = NonNullable<RouteCandidate['geometryQuality']>;

type RoutePathPart = {
  path: LatLng[];
  mode?: SegmentMode;
  quality?: GeometryQuality;
  /** Per-segment slope (walk only), used for color ramp. */
  slopePercent?: number;
};

type KakaoLatLng = {
  getLat: () => number;
  getLng: () => number;
};

type KakaoLatLngBounds = {
  extend: (latlng: KakaoLatLng) => void;
};

type KakaoMapInstance = {
  setBounds: (
    bounds: KakaoLatLngBounds,
    paddingTop?: number,
    paddingRight?: number,
    paddingBottom?: number,
    paddingLeft?: number,
  ) => void;
  setCenter: (latlng: KakaoLatLng) => void;
  setLevel: (level: number) => void;
  relayout: () => void;
  setDraggable: (draggable: boolean) => void;
  setZoomable: (zoomable: boolean) => void;
};

type KakaoMapGraphic = {
  setMap: (map: KakaoMapInstance | null) => void;
};

type KakaoPolyline = KakaoMapGraphic;
type KakaoPolygon = KakaoMapGraphic;

type KakaoCustomOverlay = KakaoMapGraphic & {
  setPosition: (latlng: KakaoLatLng) => void;
};

type KakaoEventApi = {
  addListener: (target: object, type: 'click', handler: () => void) => void;
  removeListener: (target: object, type: 'click', handler: () => void) => void;
};

type KakaoMapsApi = {
  LatLng: new (lat: number, lng: number) => KakaoLatLng;
  LatLngBounds: new () => KakaoLatLngBounds;
  Map: new (
    container: HTMLElement,
    options: {
      center: KakaoLatLng;
      level: number;
      draggable?: boolean;
      scrollwheel?: boolean;
    },
  ) => KakaoMapInstance;
  Polyline: new (options: {
    path: KakaoLatLng[];
    strokeWeight: number;
    strokeColor: string;
    strokeOpacity: number;
    strokeStyle?: string;
    clickable?: boolean;
    zIndex?: number;
  }) => KakaoPolyline;
  Polygon: new (options: {
    path: KakaoLatLng[];
    strokeWeight: number;
    strokeColor: string;
    strokeOpacity: number;
    fillColor: string;
    fillOpacity: number;
    zIndex?: number;
  }) => KakaoPolygon;
  CustomOverlay: new (options: {
    position: KakaoLatLng;
    content: HTMLElement;
    xAnchor?: number;
    yAnchor?: number;
    zIndex?: number;
  }) => KakaoCustomOverlay;
  event: KakaoEventApi;
};

type KakaoNamespace = {
  maps: KakaoMapsApi;
};

type MapListener = {
  target: object;
  handler: () => void;
};

const MODE_COLOR: Record<SegmentMode, string> = {
  walk: '#16a34a',
  bus: '#3182f6',
  subway: '#7c3aed',
  transfer: '#64748b',
};

/**
 * QGIS-style slope severity color ramp for walking segments.
 * - ≤2%  gentle         → green
 * - ≤5%  moderate       → yellow
 * - ≤8%  steep          → orange
 * - >8%  very steep     → red
 * Falls back to the default walk green when no terrain data is available.
 */
const SLOPE_COLOR_RAMP: Array<{ max: number; color: string; label: string }> = [
  { max: 2, color: '#2ca25f', label: '완만' },
  { max: 5, color: '#f2cf4a', label: '보통' },
  { max: 8, color: '#f28e2b', label: '급경사' },
  { max: Infinity, color: '#d73027', label: '매우 급경사' },
];

export function slopeColor(
  slopePercent: number | undefined | null,
): string {
  if (slopePercent === undefined || slopePercent === null) return MODE_COLOR.walk;
  const abs = Math.abs(slopePercent);
  for (const band of SLOPE_COLOR_RAMP) {
    if (abs <= band.max) return band.color;
  }
  return SLOPE_COLOR_RAMP[SLOPE_COLOR_RAMP.length - 1].color;
}

export function slopeLabel(
  slopePercent: number | undefined | null,
): string {
  if (slopePercent === undefined || slopePercent === null) return '';
  const abs = Math.abs(slopePercent);
  for (const band of SLOPE_COLOR_RAMP) {
    if (abs <= band.max) return band.label;
  }
  return SLOPE_COLOR_RAMP[SLOPE_COLOR_RAMP.length - 1].label;
}

export { SLOPE_COLOR_RAMP };

const DEFAULT_ROUTE_COLOR = '#3182f6';
const ALTERNATIVE_ROUTE_COLOR = '#64748b';
const SHADOW_FILL = '#8290a8';
const SHADOW_STROKE = '#64748b';
const SHADED_ROUTE_COLOR = '#00b84a';
const SUN_EXPOSED_ROUTE_COLOR = '#ff5a1f';

function isKakaoNamespace(value: unknown): value is KakaoNamespace {
  if (!value || typeof value !== 'object') return false;
  const maps = (value as { maps?: unknown }).maps;
  if (!maps || typeof maps !== 'object') return false;
  const api = maps as Record<string, unknown>;
  return (
    typeof api.LatLng === 'function'
    && typeof api.LatLngBounds === 'function'
    && typeof api.Map === 'function'
    && typeof api.Polyline === 'function'
    && typeof api.Polygon === 'function'
    && typeof api.CustomOverlay === 'function'
    && typeof api.event === 'object'
    && api.event !== null
    && typeof (api.event as KakaoEventApi).addListener === 'function'
    && typeof (api.event as KakaoEventApi).removeListener === 'function'
  );
}

function isValidPoint(point: LatLng): boolean {
  return (
    Number.isFinite(point.lat)
    && Number.isFinite(point.lng)
    && point.lat >= -90
    && point.lat <= 90
    && point.lng >= -180
    && point.lng <= 180
  );
}

function validPath(path: LatLng[] | undefined, minimumLength = 2): LatLng[] | null {
  if (!path || path.length < minimumLength || !path.every(isValidPoint)) {
    return null;
  }
  return path;
}

function segmentPathParts(route: RouteCandidate): RoutePathPart[] {
  const terrainParts = route.terrain?.status === 'estimated_90m'
    ? (route.terrain.slopeSegments ?? []).flatMap<RoutePathPart>((segment) => {
      const path = validPath([segment.start, segment.end]);
      return path
        ? [{
            path,
            mode: 'walk',
            quality: 'exact',
            slopePercent: segment.slopePercent,
          }]
        : [];
    })
    : [];
  const routeParts = route.segments.flatMap<RoutePathPart>((segment) => {
    if (segment.mode === 'walk' && terrainParts.length > 0) return [];
    const path = validPath(segment.path);
    if (!path) return [];
    return [{
      path,
      mode: segment.mode,
      quality: segment.geometryQuality ?? route.geometryQuality,
    }];
  });
  return [...routeParts, ...terrainParts];
}

function alternativeRoutePathParts(route: RouteCandidate): RoutePathPart[] {
  const routePath = validPath(route.path);
  return routePath
    ? [{ path: routePath, quality: route.geometryQuality }]
    : segmentPathParts(route);
}

function collectSelectedRoutePoints(route: RouteCandidate | undefined): LatLng[] {
  if (!route) return [];
  const main = validPath(route.path);
  if (main) return [...main];
  return segmentPathParts(route).flatMap((part) => part.path);
}

function buildFitPoints(
  origin: Place | null,
  destination: Place | null,
  selectedRoute: RouteCandidate | undefined,
): LatLng[] {
  const points: LatLng[] = [];
  // Origin/destination markers must always stay inside the fitted bounds.
  if (origin && isValidPoint(origin)) points.push(origin);
  if (destination && isValidPoint(destination)) points.push(destination);
  points.push(...collectSelectedRoutePoints(selectedRoute));
  return points;
}

function routeGeometryFitKey(route: RouteCandidate | undefined): string {
  const points = collectSelectedRoutePoints(route);
  if (!route || points.length === 0) {
    return `${route?.id ?? 'none'}|empty|${route?.geometryQuality ?? ''}`;
  }
  const first = points[0];
  const mid = points[Math.floor(points.length / 2)];
  const last = points[points.length - 1];
  return [
    route.id,
    route.geometryQuality ?? '',
    String(points.length),
    `${first.lat.toFixed(5)},${first.lng.toFixed(5)}`,
    `${mid.lat.toFixed(5)},${mid.lng.toFixed(5)}`,
    `${last.lat.toFixed(5)},${last.lng.toFixed(5)}`,
  ].join('|');
}

const TOP_MARKER_SAFE_PAD = 24;
const BOTTOM_MARKER_SAFE_PAD = 32;
const SIDE_PAD = 24;
const MIN_VISIBLE_MAP_PX = 100;

const TOP_OVERLAY_SELECTORS = [
  '.map-first__top',
  '.map-first__search',
  '.map-first__search--compact',
  '.map-first__context',
  '.map-first__chip-row',
] as const;

const BOTTOM_OVERLAY_SELECTORS = [
  '.map-first__drawer-panel',
  '.map-first__sheet',
] as const;

function isDisplayedOverlay(el: Element): el is HTMLElement {
  if (!(el instanceof HTMLElement)) return false;
  const style = window.getComputedStyle(el);
  if (style.display === 'none' || style.visibility === 'hidden') return false;
  if (Number(style.opacity) === 0) return false;
  const rect = el.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}

function queryVisibleOverlays(selectors: readonly string[]): HTMLElement[] {
  const found: HTMLElement[] = [];
  selectors.forEach((selector) => {
    document.querySelectorAll(selector).forEach((el) => {
      if (isDisplayedOverlay(el)) found.push(el);
    });
  });
  return found;
}

function computeVisibleAreaPaddings(mapEl: HTMLElement): {
  top: number;
  right: number;
  bottom: number;
  left: number;
} {
  const mapRect = mapEl.getBoundingClientRect();
  const height = mapEl.clientHeight || mapRect.height || 0;

  let topCovered = 0;
  queryVisibleOverlays(TOP_OVERLAY_SELECTORS).forEach((overlay) => {
    const rect = overlay.getBoundingClientRect();
    const overlap =
      Math.min(rect.bottom, mapRect.bottom) - Math.max(rect.top, mapRect.top);
    if (overlap <= 0) return;
    topCovered = Math.max(topCovered, rect.bottom - mapRect.top);
  });

  let bottomCovered = 0;
  // Prefer an open drawer panel over the route sheet when both exist.
  const bottomOverlays = queryVisibleOverlays(BOTTOM_OVERLAY_SELECTORS);
  const drawer = bottomOverlays.find((el) =>
    el.classList.contains('map-first__drawer-panel'),
  );
  const sheet = bottomOverlays.find((el) =>
    el.classList.contains('map-first__sheet'),
  );
  const bottomOverlay = drawer ?? sheet ?? null;
  if (bottomOverlay) {
    const rect = bottomOverlay.getBoundingClientRect();
    const overlap =
      Math.min(rect.bottom, mapRect.bottom) - Math.max(rect.top, mapRect.top);
    if (overlap > 0) {
      bottomCovered = Math.max(0, mapRect.bottom - rect.top);
    }
  }

  let top = Math.max(
    TOP_MARKER_SAFE_PAD,
    Math.round(Math.max(0, topCovered) + TOP_MARKER_SAFE_PAD),
  );
  let bottom = Math.max(
    BOTTOM_MARKER_SAFE_PAD,
    Math.round(Math.max(0, bottomCovered) + BOTTOM_MARKER_SAFE_PAD),
  );

  // Keep a usable map strip, but prefer preserving overlay clearance over
  // the older height-120 clamp that trimmed needed padding too aggressively.
  const minVisible = Math.min(
    Math.max(MIN_VISIBLE_MAP_PX, Math.round(height * 0.2)),
    Math.max(MIN_VISIBLE_MAP_PX, height - 40),
  );
  const maximumCombinedPadding = Math.max(0, height - minVisible);
  if (height > 0 && top + bottom > maximumCombinedPadding) {
    const scale = maximumCombinedPadding / (top + bottom);
    top = Math.max(0, Math.round(top * scale));
    bottom = Math.max(0, Math.round(bottom * scale));
  }

  return {
    top,
    right: SIDE_PAD,
    bottom,
    left: SIDE_PAD,
  };
}

function toKakaoLatLng(maps: KakaoMapsApi, point: LatLng): KakaoLatLng {
  return new maps.LatLng(point.lat, point.lng);
}

function tupleToPoint(coords: LngLatTuple): LatLng | null {
  const point = { lat: coords[1], lng: coords[0] };
  return isValidPoint(point) ? point : null;
}

function createEndpointContent(
  kind: 'origin' | 'dest',
  prefix: string,
  placeName: string,
): HTMLDivElement {
  const root = document.createElement('div');
  root.className = `map-first__kakao-marker map-first__kakao-marker--${kind}`;
  root.setAttribute('aria-label', `${prefix} ${placeName}`);

  const pin = document.createElement('span');
  pin.className = 'map-first__kakao-marker-pin';
  pin.setAttribute('aria-hidden', 'true');

  const label = document.createElement('span');
  label.className = 'map-first__kakao-marker-label';
  label.textContent = `${prefix} · ${placeName}`;

  root.append(pin, label);
  return root;
}

function createUserContent(): HTMLDivElement {
  const root = document.createElement('div');
  root.className = 'map-first__kakao-user';
  root.setAttribute('aria-label', '현재 위치');

  const dot = document.createElement('span');
  dot.className = 'map-first__kakao-user-dot';
  dot.setAttribute('aria-hidden', 'true');
  root.append(dot);
  return root;
}

function createFacilityContent(label: string, detail: string): HTMLDivElement {
  const root = document.createElement('div');
  root.className = 'map-first__kakao-facility';
  root.setAttribute('aria-label', `${label} ${detail}`);

  const icon = document.createElement('span');
  icon.className = 'map-first__kakao-facility-icon';
  icon.setAttribute('aria-hidden', 'true');
  icon.textContent = label === '승강기' ? '↕' : '저';

  const copy = document.createElement('span');
  copy.className = 'map-first__kakao-facility-label';
  copy.textContent = `${label} · ${detail}`;
  root.append(icon, copy);
  return root;
}

function strokeStyle(quality: GeometryQuality | undefined): string {
  return quality === 'exact' ? 'solid' : 'shortdash';
}

/**
 * Production-data-only Kakao map surface.
 * Every route, marker, shadow, and shade segment comes from the supplied domain data.
 */
const KakaoMap = forwardRef<KakaoMapHandle, KakaoMapProps>(function KakaoMap(
  {
    origin,
    destination,
    recommendations,
    selectedRouteId,
    onSelectRoute,
    showFacilities = false,
    layoutFitKey = '',
  },
  ref,
) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapsRef = useRef<KakaoMapsApi | null>(null);
  const mapRef = useRef<KakaoMapInstance | null>(null);
  const readyRef = useRef(false);
  const graphicsRef = useRef<KakaoMapGraphic[]>([]);
  const listenersRef = useRef<MapListener[]>([]);
  const userRef = useRef<KakaoCustomOverlay | null>(null);
  const pendingUserLocationRef = useRef<LngLatTuple | null>(null);
  const locationRafRef = useRef<number | null>(null);
  const fitRafRef = useRef<number | null>(null);
  const lastFitKeyRef = useRef<string | null>(null);
  const propsRef = useRef({
    origin,
    destination,
    recommendations,
    selectedRouteId,
    onSelectRoute,
    showFacilities,
    layoutFitKey,
  });
  propsRef.current = {
    origin,
    destination,
    recommendations,
    selectedRouteId,
    onSelectRoute,
    showFacilities,
    layoutFitKey,
  };

  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');

  const cancelLocationRaf = () => {
    if (locationRafRef.current !== null) {
      cancelAnimationFrame(locationRafRef.current);
      locationRafRef.current = null;
    }
  };

  const cancelFitRaf = () => {
    if (fitRafRef.current !== null) {
      cancelAnimationFrame(fitRafRef.current);
      fitRafRef.current = null;
    }
  };

  const clearRouteGraphics = () => {
    const maps = mapsRef.current;
    if (maps) {
      listenersRef.current.forEach(({ target, handler }) => {
        maps.event.removeListener(target, 'click', handler);
      });
    }
    listenersRef.current = [];
    graphicsRef.current.forEach((graphic) => graphic.setMap(null));
    graphicsRef.current = [];
  };

  const addGraphic = <T extends KakaoMapGraphic>(graphic: T): T => {
    graphic.setMap(mapRef.current);
    graphicsRef.current.push(graphic);
    return graphic;
  };

  const addEndpoint = (
    maps: KakaoMapsApi,
    place: Place | null,
    kind: 'origin' | 'dest',
  ) => {
    if (!place || !isValidPoint(place)) return;
    const prefix = kind === 'origin' ? '출발' : '도착';
    addGraphic(new maps.CustomOverlay({
      position: toKakaoLatLng(maps, place),
      content: createEndpointContent(kind, prefix, place.name),
      xAnchor: 0.5,
      yAnchor: 1,
      zIndex: 7,
    }));
  };

  const addAlternativeRoutes = (
    maps: KakaoMapsApi,
    routes: ScoredRoute[],
    selectedId: string | null,
    selectRoute: (routeId: string) => void,
    boundsPoints: LatLng[],
  ) => {
    routes.forEach(({ route }) => {
      const parts = alternativeRoutePathParts(route);
      parts.forEach(({ path, quality }) => {
        boundsPoints.push(...path);
        if (route.id === selectedId) return;

        const line = addGraphic(new maps.Polyline({
          path: path.map((point) => toKakaoLatLng(maps, point)),
          strokeWeight: 6,
          strokeColor: ALTERNATIVE_ROUTE_COLOR,
          strokeOpacity: 0.38,
          strokeStyle: strokeStyle(quality),
          clickable: true,
          zIndex: 2,
        }));
        const handler = () => selectRoute(route.id);
        maps.event.addListener(line, 'click', handler);
        listenersRef.current.push({ target: line, handler });
      });
    });
  };

  const addSelectedRoute = (
    maps: KakaoMapsApi,
    route: RouteCandidate | undefined,
  ) => {
    if (!route) return;
    const routePath = validPath(route.path);
    const segmentParts = segmentPathParts(route);

    const addRoutePart = (
      { path, mode, quality, slopePercent }: RoutePathPart,
      includeOutline: boolean,
    ) => {
      const kakaoPath = path.map((point) => toKakaoLatLng(maps, point));
      const style = strokeStyle(quality);
      // Walk segments use slope-dependent color ramp; other modes keep fixed colors.
      const color = mode === 'walk'
        ? slopeColor(slopePercent)
        : mode ? MODE_COLOR[mode] ?? DEFAULT_ROUTE_COLOR : DEFAULT_ROUTE_COLOR;
      if (includeOutline) {
        addGraphic(new maps.Polyline({
          path: kakaoPath,
          strokeWeight: 11,
          strokeColor: '#ffffff',
          strokeOpacity: 0.88,
          strokeStyle: style,
          zIndex: 4,
        }));
      }
      addGraphic(new maps.Polyline({
        path: kakaoPath,
        strokeWeight: 6,
        strokeColor: color,
        strokeOpacity: 0.96,
        strokeStyle: style,
        zIndex: 5,
      }));
    };

    if (routePath) {
      addRoutePart(
        { path: routePath, quality: route.geometryQuality },
        true,
      );
      segmentParts.forEach((part) => addRoutePart(part, false));
      return;
    }
    segmentParts.forEach((part) => addRoutePart(part, true));
  };

  const addShadeOverlay = (
    maps: KakaoMapsApi,
    route: RouteCandidate | undefined,
    boundsPoints: LatLng[],
  ) => {
    // 실제 shade 결과가 있으면 자동 표시하고, 없으면 layer만 조용히 생략한다.
    if (!route?.shade) return;
    if (
      route.shade.status !== 'estimated_demo'
      && route.shade.status !== 'estimated_public'
    ) return;

    route.shade.shadowPolygons.forEach((rawPolygon) => {
      const polygon = validPath(rawPolygon, 3);
      if (!polygon) return;
      boundsPoints.push(...polygon);
      addGraphic(new maps.Polygon({
        path: polygon.map((point) => toKakaoLatLng(maps, point)),
        strokeWeight: 1,
        strokeColor: SHADOW_STROKE,
        strokeOpacity: 0.35,
        fillColor: SHADOW_FILL,
        fillOpacity: 0.3,
        zIndex: 1,
      }));
    });

    route.shade.pathSegments.forEach((segment) => {
      if (!isValidPoint(segment.start) || !isValidPoint(segment.end)) return;
      addGraphic(new maps.Polyline({
        path: [
          toKakaoLatLng(maps, segment.start),
          toKakaoLatLng(maps, segment.end),
        ],
        strokeWeight: 8,
        strokeColor: segment.shaded
          ? SHADED_ROUTE_COLOR
          : SUN_EXPOSED_ROUTE_COLOR,
        strokeOpacity: 0.95,
        strokeStyle: 'solid',
        zIndex: 3,
      }));
    });
  };

  const addFacilityOverlays = (
    maps: KakaoMapsApi,
    route: RouteCandidate | undefined,
    visible: boolean,
  ) => {
    if (!visible || !route) return;
    const rendered = new Set<string>();

    route.segments.forEach((segment) => {
      const path = validPath(segment.path, 1);
      if (!path) return;

      let label: string | null = null;
      let detail: string | null = null;
      if (segment.mode === 'subway' && segment.hasElevator === true) {
        label = '승강기';
        detail = segment.stationName ?? segment.description;
      } else if (segment.mode === 'bus' && segment.isLowFloorBus === true) {
        label = '저상버스';
        detail = segment.busRouteName ?? segment.description;
      }
      if (!label || !detail) return;

      const anchor = path[0];
      const key = `${label}:${detail}:${anchor.lat}:${anchor.lng}`;
      if (rendered.has(key)) return;
      rendered.add(key);
      addGraphic(new maps.CustomOverlay({
        position: toKakaoLatLng(maps, anchor),
        content: createFacilityContent(label, detail),
        xAnchor: 0.5,
        yAnchor: 1.25,
        zIndex: 6,
      }));
    });
  };

  const fitDataBounds = (
    maps: KakaoMapsApi,
    map: KakaoMapInstance,
    points: LatLng[],
    fitKey: string,
  ) => {
    if (lastFitKeyRef.current === fitKey) return;
    lastFitKeyRef.current = fitKey;
    cancelFitRaf();

    fitRafRef.current = requestAnimationFrame(() => {
      fitRafRef.current = null;
      if (mapRef.current !== map || mapsRef.current !== maps) return;
      map.relayout();

      if (points.length === 0) {
        map.setCenter(new maps.LatLng(DISTRICT.center.lat, DISTRICT.center.lng));
        map.setLevel(DISTRICT.defaultZoom);
        return;
      }
      if (points.length === 1) {
        map.setCenter(toKakaoLatLng(maps, points[0]));
        map.setLevel(4);
        return;
      }

      const bounds = new maps.LatLngBounds();
      points.forEach((point) => bounds.extend(toKakaoLatLng(maps, point)));
      const mapEl = containerRef.current;
      const padding = mapEl
        ? computeVisibleAreaPaddings(mapEl)
        : {
            top: TOP_MARKER_SAFE_PAD,
            right: SIDE_PAD,
            bottom: BOTTOM_MARKER_SAFE_PAD,
            left: SIDE_PAD,
          };
      map.setBounds(
        bounds,
        padding.top,
        padding.right,
        padding.bottom,
        padding.left,
      );
    });
  };

  const renderMapData = (
    nextOrigin: Place | null,
    nextDestination: Place | null,
    routes: ScoredRoute[],
    selectedId: string | null,
    selectRoute: (routeId: string) => void,
    facilitiesVisible: boolean,
    nextLayoutFitKey: string,
  ) => {
    const maps = mapsRef.current;
    const map = mapRef.current;
    if (!maps || !map) return;

    clearRouteGraphics();
    const boundsPoints: LatLng[] = [];
    const selectedRoute = routes.find(({ route }) => route.id === selectedId)?.route;
    addShadeOverlay(maps, selectedRoute, boundsPoints);
    addAlternativeRoutes(maps, routes, selectedId, selectRoute, boundsPoints);
    addSelectedRoute(maps, selectedRoute);
    addFacilityOverlays(maps, selectedRoute, facilitiesVisible);
    addEndpoint(maps, nextOrigin, 'origin');
    addEndpoint(maps, nextDestination, 'dest');

    const fitPoints = buildFitPoints(nextOrigin, nextDestination, selectedRoute);
    const heightBucket = Math.round((containerRef.current?.clientHeight ?? 0) / 40);
    const fitKey = [
      selectedId ?? 'none',
      routeGeometryFitKey(selectedRoute),
      nextLayoutFitKey,
      String(heightBucket),
    ].join('\u001f');
    fitDataBounds(maps, map, fitPoints, fitKey);
  };

  const removeUserOverlay = () => {
    userRef.current?.setMap(null);
    userRef.current = null;
  };

  const centerMapOn = (map: KakaoMapInstance, position: KakaoLatLng) => {
    cancelLocationRaf();
    map.relayout();
    map.setLevel(3);
    map.setCenter(position);

    locationRafRef.current = requestAnimationFrame(() => {
      locationRafRef.current = null;
      if (mapRef.current !== map) return;
      map.relayout();
      map.setLevel(3);
      map.setCenter(position);
    });
  };

  const applyUserLocation = (coords: LngLatTuple): boolean => {
    const point = tupleToPoint(coords);
    const maps = mapsRef.current;
    const map = mapRef.current;
    if (!point || !maps || !map) return false;

    const position = toKakaoLatLng(maps, point);
    if (userRef.current) {
      userRef.current.setPosition(position);
    } else {
      userRef.current = new maps.CustomOverlay({
        position,
        content: createUserContent(),
        xAnchor: 0.5,
        yAnchor: 0.5,
        zIndex: 8,
      });
      userRef.current.setMap(map);
    }
    centerMapOn(map, position);
    return true;
  };

  useImperativeHandle(ref, () => ({
    flyToUserLocation(coords) {
      if (!tupleToPoint(coords)) {
        pendingUserLocationRef.current = null;
        return;
      }
      pendingUserLocationRef.current = coords;
      if (!readyRef.current) return;
      if (applyUserLocation(coords)) {
        pendingUserLocationRef.current = null;
      }
    },
    clearUserLocation() {
      pendingUserLocationRef.current = null;
      removeUserOverlay();
    },
  }));

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    if (!hasKakaoKey()) {
      setStatus('error');
      return;
    }

    let cancelled = false;
    let resizeObserver: ResizeObserver | null = null;

    const fail = () => {
      if (cancelled) return;
      readyRef.current = false;
      setStatus('error');
    };

    // loadKakaoMaps 내부 1회 재시도까지 포함한 최종 결과만 반영한다.
    // 재시도 성공 시 아래 setStatus('ready')로 오류 폴백을 해제한다.
    setStatus('loading');
    void loadKakaoMaps()
      .then((loaded: unknown) => {
        if (cancelled || !containerRef.current || !isKakaoNamespace(loaded)) {
          if (!cancelled) fail();
          return;
        }

        const maps = loaded.maps;
        mapsRef.current = maps;
        const map = new maps.Map(containerRef.current, {
          center: new maps.LatLng(DISTRICT.center.lat, DISTRICT.center.lng),
          level: DISTRICT.defaultZoom,
          draggable: true,
          scrollwheel: true,
        });
        map.setDraggable(true);
        map.setZoomable(true);
        mapRef.current = map;
        readyRef.current = true;

        const current = propsRef.current;
        renderMapData(
          current.origin,
          current.destination,
          current.recommendations,
          current.selectedRouteId,
          current.onSelectRoute,
          current.showFacilities,
          current.layoutFitKey,
        );
        const pending = pendingUserLocationRef.current;
        if (pending && applyUserLocation(pending)) {
          pendingUserLocationRef.current = null;
        }
        setStatus('ready');

        resizeObserver = new ResizeObserver(() => {
          map.relayout();
          const latest = propsRef.current;
          const selected = latest.recommendations.find(
            ({ route }) => route.id === latest.selectedRouteId,
          )?.route;
          const fitPoints = buildFitPoints(
            latest.origin,
            latest.destination,
            selected,
          );
          const heightBucket = Math.round(
            (containerRef.current?.clientHeight ?? 0) / 40,
          );
          const fitKey = [
            latest.selectedRouteId ?? 'none',
            routeGeometryFitKey(selected),
            latest.layoutFitKey,
            String(heightBucket),
          ].join('\u001f');
          // Allow a fresh fit when the viewport bucket changes.
          if (lastFitKeyRef.current !== fitKey) {
            lastFitKeyRef.current = null;
            fitDataBounds(maps, map, fitPoints, fitKey);
          }
        });
        resizeObserver.observe(containerRef.current);
      })
      .catch(fail);

    return () => {
      cancelled = true;
      resizeObserver?.disconnect();
      cancelLocationRaf();
      cancelFitRaf();
      readyRef.current = false;
      lastFitKeyRef.current = null;
      pendingUserLocationRef.current = null;
      clearRouteGraphics();
      removeUserOverlay();
      mapRef.current = null;
      mapsRef.current = null;
      container.replaceChildren();
    };
    // Map creation is intentionally mount-only; the data effect below owns updates.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!readyRef.current || status !== 'ready') return;
    renderMapData(
      origin,
      destination,
      recommendations,
      selectedRouteId,
      onSelectRoute,
      showFacilities,
      layoutFitKey,
    );
    // Map data helpers use refs and are intentionally recreated with the latest props.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    origin,
    destination,
    recommendations,
    selectedRouteId,
    onSelectRoute,
    showFacilities,
    layoutFitKey,
    status,
  ]);

  return (
    <div
      className="map-first__map map-first__map--kakao"
      role="region"
      aria-label="지도"
    >
      <div ref={containerRef} className="map-first__map-canvas map-first__kakao-canvas" />
      {status === 'loading' && (
        <div className="map-first__map-status" role="status">
          지도 불러오는 중…
        </div>
      )}
      {status === 'error' && (
        <div className="map-first__map-status map-first__map-status--error" role="alert">
          카카오맵을 불러오지 못했어요. 지도 키·허용 도메인·네트워크를 확인해 주세요.
        </div>
      )}
    </div>
  );
});

export default KakaoMap;
