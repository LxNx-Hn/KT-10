import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { hasKakaoKey, loadKakaoMaps } from '@/map/kakaoLoader';
import {
  DEMO_ORIGIN,
  DEMO_ROUTES,
  INITIAL_CENTER,
  getDemoPath,
  type LngLatTuple,
  type MapProfileId,
} from './mapDemoData';

/** Imperative map API shared with MapFirstPrototype via ref */
export type KakaoMapHandle = {
  flyToUserLocation: (coords: LngLatTuple) => void;
  flyToDemoOrigin: () => void;
};

type KakaoMapProps = {
  profile: MapProfileId;
  showFacilities: boolean;
  reversed: boolean;
  routeCoordinates?: LngLatTuple[] | null;
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
  getDraggable: () => boolean;
  setZoomable: (zoomable: boolean) => void;
  getZoomable: () => boolean;
};

type KakaoPolyline = {
  setMap: (map: KakaoMapInstance | null) => void;
  setPath: (path: KakaoLatLng[]) => void;
};

type KakaoCustomOverlay = {
  setMap: (map: KakaoMapInstance | null) => void;
  setPosition: (latlng: KakaoLatLng) => void;
};

type KakaoMarker = {
  setMap: (map: KakaoMapInstance | null) => void;
  setClickable: (clickable: boolean) => void;
};

type KakaoInfoWindow = {
  open: (map: KakaoMapInstance, marker: KakaoMarker) => void;
  close: () => void;
  setContent: (content: string | HTMLElement) => void;
  setZIndex: (zIndex: number) => void;
};

type KakaoEventApi = {
  addListener: (target: KakaoMarker, type: 'click', handler: () => void) => void;
  removeListener: (target: KakaoMarker, type: 'click', handler: () => void) => void;
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
    zIndex?: number;
  }) => KakaoPolyline;
  CustomOverlay: new (options: {
    position: KakaoLatLng;
    content: HTMLElement | string;
    xAnchor?: number;
    yAnchor?: number;
    zIndex?: number;
  }) => KakaoCustomOverlay;
  Marker: new (options: {
    map?: KakaoMapInstance;
    position: KakaoLatLng;
    title?: string;
    clickable?: boolean;
    zIndex?: number;
  }) => KakaoMarker;
  InfoWindow: new (options: {
    content?: string | HTMLElement;
    removable?: boolean;
  }) => KakaoInfoWindow;
  event: KakaoEventApi;
};

type KakaoNamespace = {
  maps: KakaoMapsApi;
};

type FacilityMarkerEntry = {
  marker: KakaoMarker;
  handler: () => void;
};

function isKakaoNamespace(value: unknown): value is KakaoNamespace {
  if (!value || typeof value !== 'object') return false;
  const maps = (value as { maps?: unknown }).maps;
  if (!maps || typeof maps !== 'object') return false;
  const api = maps as Record<string, unknown>;
  return (
    typeof api.LatLng === 'function' &&
    typeof api.LatLngBounds === 'function' &&
    typeof api.Map === 'function' &&
    typeof api.Polyline === 'function' &&
    typeof api.CustomOverlay === 'function' &&
    typeof api.Marker === 'function' &&
    typeof api.InfoWindow === 'function' &&
    typeof api.event === 'object' &&
    api.event !== null &&
    typeof (api.event as KakaoEventApi).addListener === 'function' &&
    typeof (api.event as KakaoEventApi).removeListener === 'function'
  );
}

function toKakaoLatLng(maps: KakaoMapsApi, coord: LngLatTuple): KakaoLatLng {
  return new maps.LatLng(coord[1], coord[0]);
}

/** Prefer mock recommendation coords; otherwise profile demo path. Apply reverse last. */
function resolveDisplayPath(
  profile: MapProfileId,
  reversed: boolean,
  routeCoordinates?: LngLatTuple[] | null,
): LngLatTuple[] {
  const fromStore =
    routeCoordinates && routeCoordinates.length >= 2 ? [...routeCoordinates] : null;
  const base = fromStore ?? getDemoPath(profile, false);
  return reversed ? [...base].reverse() : base;
}

function createEndpointContent(kind: 'origin' | 'dest', label: string): HTMLDivElement {
  const el = document.createElement('div');
  el.className = `map-first__kakao-marker map-first__kakao-marker--${kind}`;
  el.innerHTML = `
    <span class="map-first__kakao-marker-pin" aria-hidden="true"></span>
    <span class="map-first__kakao-marker-label">${label}</span>
  `;
  return el;
}

function createUserContent(): HTMLDivElement {
  const el = document.createElement('div');
  el.className = 'map-first__kakao-user';
  el.setAttribute('aria-label', '현재 위치');
  el.innerHTML = `<span class="map-first__kakao-user-dot" aria-hidden="true"></span>`;
  return el;
}

function createFacilityInfoContent(name: string): HTMLDivElement {
  const el = document.createElement('div');
  el.className = 'map-first__kakao-popup';

  const title = document.createElement('strong');
  title.className = 'map-first__kakao-popup-title';
  title.textContent = name;

  const note = document.createElement('p');
  note.className = 'map-first__kakao-popup-note';
  note.textContent = '데모 데이터';

  el.append(title, note);
  return el;
}

/**
 * Kakao Maps surface for the map-first prototype.
 * Renders routes, markers, and facilities via the Kakao Maps JavaScript SDK.
 */
const KakaoMap = forwardRef<KakaoMapHandle, KakaoMapProps>(function KakaoMap(
  { profile, showFacilities, reversed, routeCoordinates = null },
  ref,
) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapsRef = useRef<KakaoMapsApi | null>(null);
  const mapRef = useRef<KakaoMapInstance | null>(null);
  const readyRef = useRef(false);
  const pendingUserLocationRef = useRef<LngLatTuple | null>(null);

  const casingRef = useRef<KakaoPolyline | null>(null);
  const lineRef = useRef<KakaoPolyline | null>(null);
  const originRef = useRef<KakaoCustomOverlay | null>(null);
  const destRef = useRef<KakaoCustomOverlay | null>(null);
  const facilityMarkersRef = useRef<FacilityMarkerEntry[]>([]);
  const facilityInfoWindowRef = useRef<KakaoInfoWindow | null>(null);
  const userRef = useRef<KakaoCustomOverlay | null>(null);
  const locationRafRef = useRef<number | null>(null);

  const propsRef = useRef({ profile, reversed, routeCoordinates, showFacilities });
  propsRef.current = { profile, reversed, routeCoordinates, showFacilities };

  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');

  const fitRoute = (path: LngLatTuple[]) => {
    const maps = mapsRef.current;
    const map = mapRef.current;
    if (!maps || !map || path.length === 0) return;

    const bounds = new maps.LatLngBounds();
    path.forEach((coord) => bounds.extend(toKakaoLatLng(maps, coord)));
    map.setBounds(bounds, 180, 64, 260, 48);
  };

  const ensureRouteGraphics = (maps: KakaoMapsApi, map: KakaoMapInstance) => {
    if (!casingRef.current) {
      casingRef.current = new maps.Polyline({
        path: [],
        strokeWeight: 12,
        strokeColor: '#ffffff',
        strokeOpacity: 0.9,
        strokeStyle: 'solid',
        zIndex: 1,
      });
      casingRef.current.setMap(map);
    }

    if (!lineRef.current) {
      lineRef.current = new maps.Polyline({
        path: [],
        strokeWeight: 6,
        strokeColor: '#3182F6',
        strokeOpacity: 1,
        strokeStyle: 'solid',
        zIndex: 2,
      });
      lineRef.current.setMap(map);
    }

    if (!originRef.current) {
      originRef.current = new maps.CustomOverlay({
        position: toKakaoLatLng(maps, INITIAL_CENTER),
        content: createEndpointContent('origin', '출발'),
        xAnchor: 0.5,
        yAnchor: 1,
        zIndex: 3,
      });
      originRef.current.setMap(map);
    }

    if (!destRef.current) {
      destRef.current = new maps.CustomOverlay({
        position: toKakaoLatLng(maps, INITIAL_CENTER),
        content: createEndpointContent('dest', '도착'),
        xAnchor: 0.5,
        yAnchor: 1,
        zIndex: 3,
      });
      destRef.current.setMap(map);
    }
  };

  const updateRoute = (path: LngLatTuple[], maps: KakaoMapsApi, map: KakaoMapInstance) => {
    ensureRouteGraphics(maps, map);

    if (path.length < 2) {
      casingRef.current?.setPath([]);
      lineRef.current?.setPath([]);
      return;
    }

    const kakaoPath = path.map((coord) => toKakaoLatLng(maps, coord));
    casingRef.current?.setPath(kakaoPath);
    lineRef.current?.setPath(kakaoPath);

    originRef.current?.setPosition(toKakaoLatLng(maps, path[0]));
    destRef.current?.setPosition(toKakaoLatLng(maps, path[path.length - 1]));

    fitRoute(path);
  };

  const cancelLocationRaf = () => {
    if (locationRafRef.current !== null) {
      cancelAnimationFrame(locationRafRef.current);
      locationRafRef.current = null;
    }
  };

  const ensureFacilityInfoWindow = (maps: KakaoMapsApi): KakaoInfoWindow => {
    if (!facilityInfoWindowRef.current) {
      facilityInfoWindowRef.current = new maps.InfoWindow({ removable: true });
    }
    return facilityInfoWindowRef.current;
  };

  const openFacilityInfo = (
    maps: KakaoMapsApi,
    map: KakaoMapInstance,
    marker: KakaoMarker,
    name: string,
  ) => {
    const infoWindow = ensureFacilityInfoWindow(maps);
    infoWindow.close();
    infoWindow.setContent(createFacilityInfoContent(name));
    infoWindow.setZIndex(100);
    infoWindow.open(map, marker);
  };

  const clearFacilityMarkers = () => {
    const maps = mapsRef.current;
    facilityMarkersRef.current.forEach(({ marker, handler }) => {
      if (maps) {
        maps.event.removeListener(marker, 'click', handler);
      }
      marker.setMap(null);
    });
    facilityMarkersRef.current = [];
    facilityInfoWindowRef.current?.close();
    facilityInfoWindowRef.current = null;
  };

  const renderFacilities = (
    nextProfile: MapProfileId,
    visible: boolean,
    maps: KakaoMapsApi,
    map: KakaoMapInstance,
  ) => {
    clearFacilityMarkers();
    if (!visible) return;

    const facilities = DEMO_ROUTES[nextProfile].facilities;
    facilityMarkersRef.current = facilities.map((facility) => {
      const position = toKakaoLatLng(maps, facility.coordinates);
      const marker = new maps.Marker({
        position,
        title: facility.name,
        clickable: true,
        zIndex: 10,
      });
      marker.setMap(map);
      marker.setClickable(true);

      const handler = () => {
        openFacilityInfo(maps, map, marker, facility.name);
      };

      maps.event.addListener(marker, 'click', handler);
      return { marker, handler };
    });
  };

  const clearUserOverlay = () => {
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

  const applyUserLocation = (coords: LngLatTuple) => {
    const maps = mapsRef.current;
    const map = mapRef.current;
    if (!maps || !map) return false;

    const position = toKakaoLatLng(maps, coords);
    if (userRef.current) {
      userRef.current.setPosition(position);
    } else {
      userRef.current = new maps.CustomOverlay({
        position,
        content: createUserContent(),
        xAnchor: 0.5,
        yAnchor: 0.5,
        zIndex: 6,
      });
      userRef.current.setMap(map);
    }

    centerMapOn(map, position);
    return true;
  };

  const clearRouteGraphics = () => {
    casingRef.current?.setMap(null);
    lineRef.current?.setMap(null);
    originRef.current?.setMap(null);
    destRef.current?.setMap(null);
    casingRef.current = null;
    lineRef.current = null;
    originRef.current = null;
    destRef.current = null;
  };

  const clearAllMapObjects = () => {
    clearRouteGraphics();
    clearFacilityMarkers();
    clearUserOverlay();
  };

  useImperativeHandle(ref, () => ({
    flyToUserLocation(coords) {
      pendingUserLocationRef.current = coords;
      if (!readyRef.current || !mapRef.current || !mapsRef.current) {
        return;
      }
      applyUserLocation(coords);
      pendingUserLocationRef.current = null;
    },
    flyToDemoOrigin() {
      pendingUserLocationRef.current = null;
      cancelLocationRaf();

      const maps = mapsRef.current;
      const map = mapRef.current;
      if (!maps || !map) return;

      clearUserOverlay();
      centerMapOn(map, toKakaoLatLng(maps, DEMO_ORIGIN));
    },
  }));

  // Initialize Kakao map once (StrictMode-safe via effect-local cancelled flag)
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

    void loadKakaoMaps()
      .then((loaded: unknown) => {
        if (cancelled || !containerRef.current) return;
        if (!isKakaoNamespace(loaded)) {
          fail();
          return;
        }

        const maps = loaded.maps;
        mapsRef.current = maps;

        const map = new maps.Map(containerRef.current, {
          center: toKakaoLatLng(maps, INITIAL_CENTER),
          level: 4,
          draggable: true,
          scrollwheel: true,
        });
        map.setDraggable(true);
        map.setZoomable(true);
        mapRef.current = map;
        readyRef.current = true;

        const {
          profile: p,
          reversed: r,
          routeCoordinates: coords,
          showFacilities: facilitiesOn,
        } = propsRef.current;
        const path = resolveDisplayPath(p, r, coords);
        updateRoute(path, maps, map);
        renderFacilities(p, facilitiesOn, maps, map);
        setStatus('ready');

        resizeObserver = new ResizeObserver(() => {
          map.relayout();
        });
        resizeObserver.observe(containerRef.current);
      })
      .catch(() => {
        fail();
      });

    return () => {
      cancelled = true;
      resizeObserver?.disconnect();
      cancelLocationRaf();
      readyRef.current = false;
      pendingUserLocationRef.current = null;
      clearAllMapObjects();
      mapRef.current = null;
      mapsRef.current = null;
      container.innerHTML = '';
    };
    // Mount once — route/facility updates handled below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Update route when profile / reverse / mock path changes
  useEffect(() => {
    const maps = mapsRef.current;
    const map = mapRef.current;
    if (!maps || !map || !readyRef.current || status !== 'ready') return;

    const path = resolveDisplayPath(profile, reversed, routeCoordinates);
    updateRoute(path, maps, map);

    const pending = pendingUserLocationRef.current;
    if (pending) {
      const coords = pending;
      pendingUserLocationRef.current = null;
      requestAnimationFrame(() => {
        if (!mapRef.current) return;
        applyUserLocation(coords);
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile, reversed, routeCoordinates, status]);

  // Facility markers — rebuild when layer or profile changes
  useEffect(() => {
    const maps = mapsRef.current;
    const map = mapRef.current;
    if (!maps || !map || !readyRef.current || status !== 'ready') return;

    renderFacilities(profile, showFacilities, maps, map);
    return () => {
      clearFacilityMarkers();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile, showFacilities, status]);

  return (
    <div className="map-first__map map-first__map--kakao">
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
