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
import {
  KT_CLIMATE_SHELTER_GROUPS,
  KT_CLIMATE_SHELTER_SOURCE_LABEL,
  type ClimateShelterMarkerGroup,
} from '@/data/ktClimateShelters';
import {
  SLOPE_COLOR_RAMP,
  slopeLevelLabel,
  slopeMapColor,
} from './utils/slopeLevel';
import {
  TRANSPORT_MODE_COLOR,
  resolveSubwayLine,
  transportModeStrokeColor,
  transportModeStrokeStyle,
  type TransportSubwayLineId,
} from './transportModeVisual';

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
  /** 선택 경로 shade geometry가 있을 때만 의미가 있다. 기본 ON(기존 자동 표시). */
  showShade?: boolean;
  /** terrain.slopeSegments가 있을 때만 경사색 도보선을 그린다. 기본 ON. */
  showSlope?: boolean;
  /** Overlay layout signature (search panel / sheet / drawer) for visible-area fits. */
  layoutFitKey?: string;
  /**
   * KT 기후쉼터 marker 그룹. 기본은 정적 CSV 데이터.
   * 테스트에서 빈 배열/픽스처를 주입할 때 사용한다.
   */
  climateShelterGroups?: ClimateShelterMarkerGroup[];
};

type GeometryQuality = NonNullable<RouteCandidate['geometryQuality']>;

type RoutePathPart = {
  path: LatLng[];
  mode?: SegmentMode;
  quality?: GeometryQuality;
  /** Per-segment slope (walk only), used for color ramp. */
  slopePercent?: number;
  /** 도시철도 호선. subway segment에서만 설정. */
  subwayLineId?: TransportSubwayLineId;
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
  getLevel: () => number;
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
  setZIndex: (zIndex: number) => void;
};

type KakaoMapEventType = 'click' | 'zoom_changed';

type KakaoEventApi = {
  addListener: (
    target: object,
    type: KakaoMapEventType,
    handler: () => void,
  ) => void;
  removeListener: (
    target: object,
    type: KakaoMapEventType,
    handler: () => void,
  ) => void;
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

/**
 * KT 기후쉼터를 표시할 수 있는 최대 Kakao map level.
 * Kakao level은 값이 클수록 더 넓은 축척(zoom-out).
 * 앱 참고값: 사용자 위치 3, 단일점 4, 경로 setBounds 대략 5–7, DISTRICT.defaultZoom 9.
 * 시내 경로·주변 시설을 보는 수준(<=7)만 표시하고, 도시 전역(8+)에서는 숨겨
 * 134개 marker가 경로보다 먼저 보이지 않게 한다.
 */
export const KT_CLIMATE_SHELTER_MAX_VISIBLE_LEVEL = 7;

export function shouldShowClimateSheltersAtLevel(level: number): boolean {
  return Number.isFinite(level) && level <= KT_CLIMATE_SHELTER_MAX_VISIBLE_LEVEL;
}

const MODE_COLOR: Record<SegmentMode, string> = {
  walk: TRANSPORT_MODE_COLOR.walk,
  bus: TRANSPORT_MODE_COLOR.bus,
  subway: TRANSPORT_MODE_COLOR.subway,
  transfer: TRANSPORT_MODE_COLOR.transfer,
};

/** 구간 경사색. 값 없으면 기본 도보색. 판정은 slopeLevel 유틸과 동일. */
export function slopeColor(
  slopePercent: number | undefined | null,
): string {
  return slopeMapColor(slopePercent, MODE_COLOR.walk);
}

export function slopeLabel(
  slopePercent: number | undefined | null,
): string {
  return slopeLevelLabel(slopePercent);
}

export { SLOPE_COLOR_RAMP };

const ALTERNATIVE_ROUTE_COLOR = TRANSPORT_MODE_COLOR.transfer;
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
      subwayLineId: segment.mode === 'subway'
        ? resolveSubwayLine(segment).id
        : undefined,
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

/** 경로 위 편의시설 marker z. shelter 기본보다 살짝 위, 선택 shelter보다 아래. */
const FACILITY_OVERLAY_Z = 6;
const SHELTER_OVERLAY_Z = 5;
/** 열린 상세 bubble이 다른 쉼터/편의시설 marker에 가리지 않게. */
const SHELTER_OPEN_OVERLAY_Z = 12;

const shelterLayerPriorityByRoot = new WeakMap<
  HTMLElement,
  (open: boolean) => void
>();
const openShelterRoots = new Set<HTMLElement>();

function createElevatorFacilityIcon(): HTMLSpanElement {
  const icon = document.createElement('span');
  icon.className =
    'map-first__kakao-facility-icon map-first__kakao-facility-icon--elevator';
  icon.setAttribute('aria-hidden', 'true');
  // 저장소에 elevator SVG가 없어 인라인 pictogram(문 + 상하 화살표) 사용.
  icon.innerHTML =
    '<svg class="map-first__kakao-facility-pictogram" viewBox="0 0 16 16" width="14" height="14" focusable="false" aria-hidden="true">'
    + '<rect x="3.25" y="2" width="9.5" height="12" rx="1.1" fill="none" stroke="currentColor" stroke-width="1.35"/>'
    + '<path fill="currentColor" d="M8 3.9 6.35 5.85h3.3Z"/>'
    + '<path fill="currentColor" d="M8 12.1 6.35 10.15h3.3Z"/>'
    + '<path fill="none" stroke="currentColor" stroke-width="1.2" d="M8 6.15v3.7"/>'
    + '</svg>';
  return icon;
}

function createFacilityContent(label: string, detail: string): HTMLDivElement {
  const root = document.createElement('div');
  const kind = label === '승강기' ? 'elevator' : 'bus';
  root.className = `map-first__kakao-facility map-first__kakao-facility--${kind}`;
  root.setAttribute('aria-label', `${label} ${detail}`);

  let icon: HTMLSpanElement;
  if (label === '승강기') {
    icon = createElevatorFacilityIcon();
  } else {
    icon = document.createElement('span');
    icon.className =
      'map-first__kakao-facility-icon map-first__kakao-facility-icon--bus';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = '저';
  }

  const copy = document.createElement('span');
  copy.className = 'map-first__kakao-facility-label';
  copy.textContent = `${label} · ${detail}`;
  root.append(icon, copy);
  return root;
}

function closeOpenShelterBubbles(except?: HTMLElement) {
  for (const node of [...openShelterRoots]) {
    if (except && node === except) continue;
    node.classList.remove('map-first__kakao-shelter--open');
    const bubble = node.querySelector('.map-first__kakao-shelter-bubble');
    const toggle = node.querySelector('.map-first__kakao-shelter-marker');
    if (bubble instanceof HTMLElement) bubble.hidden = true;
    if (toggle instanceof HTMLElement) {
      toggle.setAttribute('aria-expanded', 'false');
    }
    openShelterRoots.delete(node);
    shelterLayerPriorityByRoot.get(node)?.(false);
  }
}

function createClimateShelterContent(
  group: ClimateShelterMarkerGroup,
): HTMLDivElement {
  const root = document.createElement('div');
  root.className = 'map-first__kakao-shelter';
  const names = group.shelters.map((item) => item.name).join(', ');
  const count = group.shelters.length;
  const accessibleName =
    count > 1
      ? `KT 기후쉼터 ${count}곳: ${names}`
      : `KT 기후쉼터 ${group.shelters[0]?.name ?? ''}`;

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'map-first__kakao-shelter-marker';
  button.setAttribute('aria-label', accessibleName);
  button.setAttribute('aria-expanded', 'false');
  button.textContent = '쉼';

  const bubble = document.createElement('div');
  bubble.className = 'map-first__kakao-shelter-bubble';
  bubble.hidden = true;
  bubble.setAttribute('role', 'dialog');
  bubble.setAttribute(
    'aria-label',
    count > 1 ? `KT 기후쉼터 ${count}곳` : 'KT 기후쉼터',
  );

  const title = document.createElement('strong');
  title.className = 'map-first__kakao-shelter-title';
  title.textContent =
    count > 1 ? `KT 기후쉼터 ${count}곳` : 'KT 기후쉼터';

  const list = document.createElement('ul');
  list.className = 'map-first__kakao-shelter-list';
  for (const shelter of group.shelters) {
    const item = document.createElement('li');
    const name = document.createElement('b');
    name.textContent = shelter.name;
    const address = document.createElement('span');
    address.textContent = shelter.address;
    item.append(name, address);
    list.append(item);
  }

  const source = document.createElement('em');
  source.className = 'map-first__kakao-shelter-source';
  source.textContent = KT_CLIMATE_SHELTER_SOURCE_LABEL;

  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'map-first__kakao-shelter-close';
  close.setAttribute('aria-label', '기후쉼터 정보 닫기');
  close.textContent = '×';

  bubble.append(title, list, source, close);
  root.append(button, bubble);

  const setOpen = (open: boolean) => {
    if (open) closeOpenShelterBubbles(root);
    root.classList.toggle('map-first__kakao-shelter--open', open);
    bubble.hidden = !open;
    button.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) openShelterRoots.add(root);
    else openShelterRoots.delete(root);
    shelterLayerPriorityByRoot.get(root)?.(open);
  };

  button.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    setOpen(bubble.hidden);
  });
  close.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    setOpen(false);
  });

  return root;
}

function strokeStyle(quality: GeometryQuality | undefined): string {
  return quality === 'exact' ? 'solid' : 'shortdash';
}

function partStrokeColor(part: RoutePathPart): string {
  return transportModeStrokeColor(part.mode, {
    slopePercent: part.slopePercent,
    subwayLineId: part.subwayLineId,
    slopeColorFn: slopeColor,
    walkFallback: MODE_COLOR.walk,
  });
}

function partStrokeStyle(part: RoutePathPart): string {
  return transportModeStrokeStyle(part.mode, part.quality, {
    slopePercent: part.slopePercent,
  });
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
    showShade = true,
    showSlope = true,
    layoutFitKey = '',
    climateShelterGroups = KT_CLIMATE_SHELTER_GROUPS,
  },
  ref,
) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapsRef = useRef<KakaoMapsApi | null>(null);
  const mapRef = useRef<KakaoMapInstance | null>(null);
  const readyRef = useRef(false);
  const graphicsRef = useRef<KakaoMapGraphic[]>([]);
  const shelterOverlaysRef = useRef<KakaoCustomOverlay[]>([]);
  const listenersRef = useRef<MapListener[]>([]);
  const zoomListenerRef = useRef<(() => void) | null>(null);
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
    showShade,
    showSlope,
    layoutFitKey,
    climateShelterGroups,
  });
  propsRef.current = {
    origin,
    destination,
    recommendations,
    selectedRouteId,
    onSelectRoute,
    showFacilities,
    showShade,
    showSlope,
    layoutFitKey,
    climateShelterGroups,
  };

  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [loadAttempt, setLoadAttempt] = useState(0);

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
    shelterOverlaysRef.current = [];
    openShelterRoots.clear();
  };

  const addGraphic = <T extends KakaoMapGraphic>(graphic: T): T => {
    graphic.setMap(mapRef.current);
    graphicsRef.current.push(graphic);
    return graphic;
  };

  const syncShelterOverlayVisibility = () => {
    const map = mapRef.current;
    if (!map) return;
    const visible =
      propsRef.current.showFacilities
      && shouldShowClimateSheltersAtLevel(map.getLevel());
    if (!visible) closeOpenShelterBubbles();
    for (const overlay of shelterOverlaysRef.current) {
      overlay.setMap(visible ? map : null);
    }
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
    slopeVisible: boolean,
  ) => {
    if (!route) return;
    const routePath = validPath(route.path);
    const segmentParts = segmentPathParts(route);
    // terrain.slopeSegments → LatLng start/end 구간. 있을 때만 도보 경사색을 쓴다.
    const slopeWalkParts = segmentParts.filter(
      (part) =>
        part.mode === 'walk' && typeof part.slopePercent === 'number',
    );
    const transitParts = segmentParts.filter(
      (part) => part.mode === 'bus' || part.mode === 'subway' || part.mode === 'transfer',
    );
    const hasSlopeWalk = slopeVisible && slopeWalkParts.length > 0;

    const drawOutline = (path: LatLng[], quality?: GeometryQuality) => {
      addGraphic(new maps.Polyline({
        path: path.map((point) => toKakaoLatLng(maps, point)),
        strokeWeight: 12,
        strokeColor: '#ffffff',
        strokeOpacity: 0.88,
        strokeStyle: strokeStyle(quality),
        zIndex: 4,
      }));
    };

    const drawBody = (
      part: RoutePathPart,
      zIndex: number,
      weight = 8,
    ) => {
      addGraphic(new maps.Polyline({
        path: part.path.map((point) => toKakaoLatLng(maps, point)),
        strokeWeight: weight,
        strokeColor: partStrokeColor(part),
        strokeOpacity: 0.96,
        strokeStyle: partStrokeStyle(part),
        zIndex,
      }));
    };

    if (hasSlopeWalk) {
      // 1) 외곽선만 (선택 본선은 그리지 않음 — 경사선을 덮지 않게)
      if (routePath) {
        drawOutline(routePath, route.geometryQuality);
      } else {
        segmentParts.forEach((part) => drawOutline(part.path, part.quality));
      }
      // 2) 버스·지하철(호선색)·환승
      transitParts.forEach((part) => drawBody(part, 5, 8));
      // 3) 경사도 도보 구간 (가장 위)
      slopeWalkParts.forEach((part) => drawBody(part, 6, 8));
      return;
    }

    // 이동수단별 색·패턴(도보 점선/차콜, 버스 파랑, 지하철 노선색)
    if (segmentParts.length > 0) {
      if (routePath) {
        drawOutline(routePath, route.geometryQuality);
      } else {
        segmentParts.forEach((part) => drawOutline(part.path, part.quality));
      }
      segmentParts.forEach((part) => drawBody(part, 5, 8));
      return;
    }

    if (routePath) {
      drawOutline(routePath, route.geometryQuality);
      drawBody(
        { path: routePath, quality: route.geometryQuality },
        5,
        8,
      );
    }
  };

  const addShadeOverlay = (
    maps: KakaoMapsApi,
    route: RouteCandidate | undefined,
    boundsPoints: LatLng[],
    shadeVisible: boolean,
  ) => {
    // 실제 shade geometry가 있고 사용자가 ON일 때만 표시한다.
    if (!shadeVisible || !route?.shade) return;
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
    shelterGroups: ClimateShelterMarkerGroup[],
  ) => {
    if (!visible) return;
    const rendered = new Set<string>();

    if (route) {
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
          zIndex: FACILITY_OVERLAY_Z,
        }));
      });
    }

    // KT 기후쉼터는 fitBounds에 넣지 않는다. 동일 좌표는 그룹 1개.
    // 넓은 zoom에서는 setMap(null)로만 숨기고 DOM/overlay는 재생성하지 않는다.
    shelterGroups.forEach((group) => {
      if (!Number.isFinite(group.lat) || !Number.isFinite(group.lng)) return;
      const content = createClimateShelterContent(group);
      const overlay = new maps.CustomOverlay({
        position: toKakaoLatLng(maps, { lat: group.lat, lng: group.lng }),
        content,
        xAnchor: 0.5,
        yAnchor: 1.1,
        zIndex: SHELTER_OVERLAY_Z,
      });
      shelterLayerPriorityByRoot.set(content, (open) => {
        overlay.setZIndex(open ? SHELTER_OPEN_OVERLAY_Z : SHELTER_OVERLAY_Z);
      });
      graphicsRef.current.push(overlay);
      shelterOverlaysRef.current.push(overlay);
    });
    syncShelterOverlayVisibility();
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
    shadeVisible: boolean,
    slopeVisible: boolean,
    nextLayoutFitKey: string,
    shelterGroups: ClimateShelterMarkerGroup[],
  ) => {
    const maps = mapsRef.current;
    const map = mapRef.current;
    if (!maps || !map) return;

    clearRouteGraphics();
    closeOpenShelterBubbles();
    const boundsPoints: LatLng[] = [];
    const selectedRoute = routes.find(({ route }) => route.id === selectedId)?.route;
    addShadeOverlay(maps, selectedRoute, boundsPoints, shadeVisible);
    addAlternativeRoutes(maps, routes, selectedId, selectRoute, boundsPoints);
    addSelectedRoute(maps, selectedRoute, slopeVisible);
    addFacilityOverlays(maps, selectedRoute, facilitiesVisible, shelterGroups);
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

        const onZoomChanged = () => {
          syncShelterOverlayVisibility();
        };
        maps.event.addListener(map, 'zoom_changed', onZoomChanged);
        zoomListenerRef.current = onZoomChanged;

        const current = propsRef.current;
        renderMapData(
          current.origin,
          current.destination,
          current.recommendations,
          current.selectedRouteId,
          current.onSelectRoute,
          current.showFacilities,
          current.showShade,
          current.showSlope,
          current.layoutFitKey,
          current.climateShelterGroups,
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
      const maps = mapsRef.current;
      const map = mapRef.current;
      const zoomHandler = zoomListenerRef.current;
      if (maps && map && zoomHandler) {
        maps.event.removeListener(map, 'zoom_changed', zoomHandler);
      }
      zoomListenerRef.current = null;
      readyRef.current = false;
      lastFitKeyRef.current = null;
      pendingUserLocationRef.current = null;
      clearRouteGraphics();
      removeUserOverlay();
      mapRef.current = null;
      mapsRef.current = null;
      container.replaceChildren();
    };
    // Map creation runs on mount and explicit retry only; the data effect below owns updates.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadAttempt]);

  useEffect(() => {
    if (!readyRef.current || status !== 'ready') return;
    renderMapData(
      origin,
      destination,
      recommendations,
      selectedRouteId,
      onSelectRoute,
      showFacilities,
      showShade,
      showSlope,
      layoutFitKey,
      climateShelterGroups,
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
    showShade,
    showSlope,
    layoutFitKey,
    climateShelterGroups,
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
        <div
          className="map-first__map-status"
          role="status"
          aria-live="polite"
          aria-busy="true"
        >
          <span className="map-first__map-spinner" aria-hidden="true" />
          <strong>지도 불러오는 중…</strong>
          <span>지도와 이동 정보를 준비하고 있어요.</span>
        </div>
      )}
      {status === 'error' && (
        <div className="map-first__map-status map-first__map-status--error" role="alert">
          <strong>지도를 불러오지 못했어요</strong>
          <span>네트워크 상태를 확인한 뒤 다시 시도해 주세요.</span>
          <button
            type="button"
            onClick={() => {
              setStatus('loading');
              setLoadAttempt((current) => current + 1);
            }}
          >
            지도 다시 불러오기
          </button>
        </div>
      )}
    </div>
  );
});

export default KakaoMap;
