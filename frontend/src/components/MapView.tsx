import { useEffect, useMemo, useRef, useState } from 'react';
import { useAppStore } from '@/store/appStore';
import { DISTRICT } from '@/config/district';
import { hasKakaoKey, loadKakaoMaps } from '@/map/kakaoLoader';
import type { LatLng } from '@/types';
import { serverRankedRecommendations } from '@/utils/routes';

const SHADOW_FILL = '#8290a8';
const SHADOW_STROKE = '#64748b';
const SHADED_ROUTE = '#00b84a';
const SUN_EXPOSED_ROUTE = '#ff5a1f';

/** 좌표 배열 → SVG 좌표로 정규화(폴백 스키매틱용) */
function project(
  points: LatLng[],
  w: number,
  h: number,
  pad = 24,
  boundsPoints: LatLng[] = points,
) {
  if (points.length === 0) return [];
  const lats = boundsPoints.map((p) => p.lat);
  const lngs = boundsPoints.map((p) => p.lng);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLng = Math.min(...lngs);
  const maxLng = Math.max(...lngs);
  const spanLat = maxLat - minLat || 1e-4;
  const spanLng = maxLng - minLng || 1e-4;
  return points.map((p) => ({
    x: pad + ((p.lng - minLng) / spanLng) * (w - pad * 2),
    // 위도는 위쪽이 커야 하므로 y 반전
    y: pad + (1 - (p.lat - minLat) / spanLat) * (h - pad * 2),
  }));
}

export default function MapView() {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<any>(null);
  const kakaoRef = useRef<any>(null);
  const overlaysRef = useRef<any[]>([]);
  const [fallback, setFallback] = useState(!hasKakaoKey());
  const [mapLoadFailed, setMapLoadFailed] = useState(false);
  const [mapReady, setMapReady] = useState(false);
  const [showShade, setShowShade] = useState(true);

  const origin = useAppStore((s) => s.origin);
  const destination = useAppStore((s) => s.destination);
  const recommendations = useAppStore((s) => s.recommendations);
  const selectedRouteId = useAppStore((s) => s.selectedRouteId);
  const selectRoute = useAppStore((s) => s.selectRoute);
  const selectedRoute = recommendations.find((item) => item.route.id === selectedRouteId)?.route;

  const selectedPath = useMemo<LatLng[]>(() => {
    const sel = recommendations.find((r) => r.route.id === selectedRouteId);
    if (sel?.route.path?.length) return sel.route.path;
    const pts: LatLng[] = [];
    if (origin) pts.push(origin);
    if (destination) pts.push(destination);
    return pts;
  }, [recommendations, selectedRouteId, origin, destination]);

  // Kakao 실제 지도 로드
  useEffect(() => {
    if (!hasKakaoKey()) return;
    let cancelled = false;
    loadKakaoMaps()
      .then((kakao) => {
        if (cancelled || !containerRef.current) return;
        kakaoRef.current = kakao;
        mapRef.current = new kakao.maps.Map(containerRef.current, {
          center: new kakao.maps.LatLng(DISTRICT.center.lat, DISTRICT.center.lng),
          level: DISTRICT.defaultZoom,
        });
        setMapReady(true);
      })
      .catch(() => {
        setMapReady(false);
        setMapLoadFailed(true);
        setFallback(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 실제 지도: 마커 + 선택 경로 폴리라인 갱신
  useEffect(() => {
    const kakao = kakaoRef.current;
    const map = mapRef.current;
    if (!kakao || !map) return;
    overlaysRef.current.forEach((o) => o.setMap(null));
    overlaysRef.current = [];

    const escapeHtml = (s: string) =>
      s.replace(/[&<>"']/g, (ch) =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch] as string,
      );
    const addMarker = (p: LatLng, label: string) => {
      const marker = new kakao.maps.Marker({
        position: new kakao.maps.LatLng(p.lat, p.lng),
        map,
      });
      marker.setZIndex?.(6);
      const info = new kakao.maps.InfoWindow({
        content: `<div style="padding:4px 8px">${escapeHtml(label)}</div>`,
      });
      info.setZIndex?.(7);
      info.open(map, marker);
      overlaysRef.current.push(marker, info);
    };
    if (origin) addMarker(origin, `출발: ${origin.name}`);
    if (destination) addMarker(destination, `도착: ${destination.name}`);

    // 다른 후보도 흐리게 표시하고, 선을 누르면 활성 카드와 지도를 함께 전환한다.
    for (const recommendation of recommendations) {
      if (
        recommendation.route.id === selectedRouteId
        || !recommendation.route.path
        || recommendation.route.path.length < 2
      ) {
        continue;
      }
      const alternative = new kakao.maps.Polyline({
        path: recommendation.route.path.map(
          (point) => new kakao.maps.LatLng(point.lat, point.lng),
        ),
        strokeWeight: 5,
        strokeColor: '#64748b',
        strokeOpacity: 0.35,
        strokeStyle: 'solid',
        clickable: true,
      });
      alternative.setZIndex?.(2);
      alternative.setMap(map);
      kakao.maps.event.addListener(
        alternative,
        'click',
        () => selectRoute(recommendation.route.id),
      );
      overlaysRef.current.push(alternative);
    }

    const shade = selectedRoute?.shade;
    if (
      showShade
      && (shade?.status === 'estimated_demo' || shade?.status === 'estimated_public')
    ) {
      for (const polygon of shade.shadowPolygons) {
        const overlay = new kakao.maps.Polygon({
          path: polygon.map((point) => new kakao.maps.LatLng(point.lat, point.lng)),
          strokeWeight: 1,
          strokeColor: SHADOW_STROKE,
          strokeOpacity: 0.35,
          fillColor: SHADOW_FILL,
          fillOpacity: 0.3,
        });
        overlay.setZIndex?.(1);
        overlay.setMap(map);
        overlaysRef.current.push(overlay);
      }
    }

    if (selectedPath.length >= 2) {
      const segmentPaths = (selectedRoute?.segments ?? []).filter((segment) => (segment.path?.length ?? 0) >= 2);
      if (segmentPaths.length) {
        const colors = { walk: '#16a34a', bus: '#1f6feb', subway: '#7c3aed', transfer: '#64748b' };
        for (const segment of segmentPaths) {
          const line = new kakao.maps.Polyline({
            path: segment.path!.map((p) => new kakao.maps.LatLng(p.lat, p.lng)),
            strokeWeight: 6,
            strokeColor: colors[segment.mode],
            strokeOpacity: 0.9,
            strokeStyle: segment.geometryQuality === 'estimated' ? 'shortdash' : 'solid',
          });
          line.setZIndex?.(3);
          line.setMap(map);
          overlaysRef.current.push(line);
        }
      } else {
        const line = new kakao.maps.Polyline({
          path: selectedPath.map((p) => new kakao.maps.LatLng(p.lat, p.lng)),
          strokeWeight: 6,
          strokeColor: '#1f6feb',
          strokeOpacity: 0.9,
          strokeStyle: selectedRoute?.geometryQuality === 'estimated' ? 'shortdash' : 'solid',
        });
        line.setZIndex?.(3);
        line.setMap(map);
        overlaysRef.current.push(line);
      }
      if (
        showShade
        && (shade?.status === 'estimated_demo' || shade?.status === 'estimated_public')
      ) {
        for (const segment of shade.pathSegments) {
          const line = new kakao.maps.Polyline({
            path: [
              new kakao.maps.LatLng(segment.start.lat, segment.start.lng),
              new kakao.maps.LatLng(segment.end.lat, segment.end.lng),
            ],
            strokeWeight: 8,
            strokeColor: segment.shaded ? SHADED_ROUTE : SUN_EXPOSED_ROUTE,
            strokeOpacity: 0.95,
            strokeStyle: 'solid',
          });
          line.setZIndex?.(4);
          line.setMap(map);
          overlaysRef.current.push(line);
        }
      }
      const bounds = new kakao.maps.LatLngBounds();
      selectedPath.forEach((p) => bounds.extend(new kakao.maps.LatLng(p.lat, p.lng)));
      map.setBounds(bounds);
    }
  }, [
    destination,
    origin,
    recommendations,
    mapReady,
    selectRoute,
    selectedPath,
    selectedRoute,
    selectedRouteId,
    showShade,
  ]);

  if (!fallback) {
    return (
      <div className="map" role="region" aria-label="지도">
        <div ref={containerRef} className="map__canvas" />
        <MapRoutePicker
          recommendations={recommendations}
          selectedRouteId={selectedRouteId}
          onSelect={selectRoute}
        />
        <ShadeControls
          shade={selectedRoute?.shade}
          showShade={showShade}
          onToggle={() => setShowShade((value) => !value)}
        />
        <MapDataNotice route={selectedRoute} mapSource="Kakao Maps" />
      </div>
    );
  }

  // ── 폴백 스키매틱(Kakao 키 없을 때) ──
  const W = 600;
  const H = 280;
  const shadowPolygons = (
    showShade
    && (
      selectedRoute?.shade?.status === 'estimated_demo'
      || selectedRoute?.shade?.status === 'estimated_public'
    )
  )
    ? selectedRoute.shade.shadowPolygons
    : [];
  const shadeSegments = (
    selectedRoute?.shade?.status === 'estimated_demo'
    || selectedRoute?.shade?.status === 'estimated_public'
  )
    ? selectedRoute.shade.pathSegments
    : [];
  const mapBounds = [
    ...recommendations.flatMap((recommendation) => recommendation.route.path ?? []),
    ...selectedPath,
    ...shadowPolygons.flat(),
    ...shadeSegments.flatMap((segment) => [segment.start, segment.end]),
  ];
  const pts = project(selectedPath, W, H, 24, mapBounds);
  const shadePoints = project(
    shadeSegments.flatMap((segment) => [segment.start, segment.end]),
    W,
    H,
    24,
    mapBounds,
  );
  const projectedShadows = shadowPolygons.map(
    (polygon) => project(polygon, W, H, 24, mapBounds),
  );
  const projectedAlternatives = recommendations
    .filter(({ route }) => route.id !== selectedRouteId && (route.path?.length ?? 0) >= 2)
    .map(({ route }) => ({
      routeId: route.id,
      points: project(route.path!, W, H, 24, mapBounds),
    }));
  return (
    <div className="map" role="region" aria-label="경로 약도">
      <div className="map__fallback">
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" height="100%" aria-hidden="true">
          <rect x="0" y="0" width={W} height={H} fill="#eef2f7" rx="12" />
          {projectedShadows.map((polygon, index) => (
            <polygon
              key={`building-shadow-${index}`}
              points={polygon.map((point) => `${point.x},${point.y}`).join(' ')}
              fill={SHADOW_FILL}
              fillOpacity="0.3"
              stroke={SHADOW_STROKE}
              strokeOpacity="0.35"
              strokeWidth="1"
            />
          ))}
          {projectedAlternatives.map(({ routeId, points }) => (
            <polyline
              key={`alternative-${routeId}`}
              points={points.map((point) => `${point.x},${point.y}`).join(' ')}
              fill="none"
              stroke="#64748b"
              strokeOpacity="0.35"
              strokeWidth="5"
              strokeLinecap="round"
              strokeLinejoin="round"
              onClick={() => selectRoute(routeId)}
              style={{ cursor: 'pointer' }}
            />
          ))}
          {pts.length >= 2 && (
            <polyline
              points={pts.map((p) => `${p.x},${p.y}`).join(' ')}
              fill="none"
              stroke="#1f6feb"
              strokeWidth="6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}
          {showShade && shadeSegments.map((segment, index) => {
            const start = shadePoints[index * 2];
            const end = shadePoints[index * 2 + 1];
            if (!start || !end) return null;
            return (
              <line
                key={`shade-${index}`}
                x1={start.x}
                y1={start.y}
                x2={end.x}
                y2={end.y}
                stroke={segment.shaded ? SHADED_ROUTE : SUN_EXPOSED_ROUTE}
                strokeWidth="8"
                strokeLinecap="round"
              />
            );
          })}
          {pts.map((p, i) => {
            const isStart = i === 0;
            const isEnd = i === pts.length - 1;
            if (!isStart && !isEnd) return <circle key={i} cx={p.x} cy={p.y} r="5" fill="#1f6feb" />;
            return (
              <g key={i}>
                <circle cx={p.x} cy={p.y} r="10" fill={isStart ? '#16a34a' : '#dc2626'} />
                <text x={p.x} y={p.y + 4} textAnchor="middle" fontSize="11" fill="#fff" fontWeight="700">
                  {isStart ? '출' : '도'}
                </text>
              </g>
            );
          })}
        </svg>
        <p className="map__note">
          내장 경로 약도 · {mapLoadFailed
            ? 'Kakao 지도 키 인증 또는 허용 도메인을 확인해 주세요.'
            : <><code>.env</code>에 <code>VITE_KAKAO_MAP_KEY</code>를 설정하면 실제 지도가 표시됩니다.</>}
        </p>
        <MapRoutePicker
          recommendations={recommendations}
          selectedRouteId={selectedRouteId}
          onSelect={selectRoute}
        />
        <ShadeControls
          shade={selectedRoute?.shade}
          showShade={showShade}
          onToggle={() => setShowShade((value) => !value)}
        />
        <MapDataNotice route={selectedRoute} mapSource="내장 경로 약도" />
      </div>
    </div>
  );
}

function MapRoutePicker({
  recommendations,
  selectedRouteId,
  onSelect,
}: {
  recommendations: import('@/types').ScoredRoute[];
  selectedRouteId: string | null;
  onSelect: (routeId: string) => void;
}) {
  if (recommendations.length < 2) return null;
  const ranked = serverRankedRecommendations(recommendations);
  return (
    <div className="map__route-picker" role="group" aria-label="지도에 표시할 경로">
      {ranked.map(({ route }, index) => (
        <button
          key={route.id}
          type="button"
          aria-pressed={route.id === selectedRouteId}
          onClick={() => onSelect(route.id)}
        >
          {index + 1}순위
        </button>
      ))}
    </div>
  );
}

function ShadeControls({
  shade,
  showShade,
  onToggle,
}: {
  shade?: import('@/types').RouteCandidate['shade'];
  showShade: boolean;
  onToggle: () => void;
}) {
  if (!shade || shade.status === 'unavailable' || shade.status === 'not_daylight' || shade.shadeRatio === undefined) return null;
  return (
    <div className="map__shade-controls" role="note">
      <button type="button" className="map__shade-toggle" aria-pressed={showShade} onClick={onToggle}>
        {showShade ? '그늘 오버레이 숨기기' : '그늘 오버레이 보기'}
      </button>
      <span className="map__shade-ratio">
        {shade.estimateKind === 'lower_bound' ? '확인된 건물 그늘 최소 ' : '건물 그늘 '}
        {Math.round(shade.shadeRatio * 100)}%
      </span>
      <span><i className="map__legend map__legend--shade" />그늘</span>
      <span><i className="map__legend map__legend--sun" />햇빛 노출</span>
      {shade.buildingCount !== undefined && shade.knownHeightBuildingCount !== undefined && (
        <span>
          건물 높이 {shade.knownHeightBuildingCount}/{shade.buildingCount}건 확인
        </span>
      )}
      <small>
        {shade.status === 'estimated_public'
          ? 'VWorld 공공 건물 도형·확인된 높이로 계산했습니다. 나무 그늘과 지형 그림자는 포함하지 않습니다.'
          : 'VWorld 건물 높이 기준 계산 정보입니다. 나무 그늘과 지형 그림자는 포함하지 않습니다.'}
      </small>
    </div>
  );
}

function MapDataNotice({
  route,
  mapSource,
}: {
  route?: import('@/types').RouteCandidate;
  mapSource: string;
}) {
  const sources = route?.sources ?? [];
  const terrain = route?.terrain;
  const sourceFacts = [
    ...(sources.length ? [`경로: ${sources.join(' · ')}`] : []),
    `지도: ${mapSource}`,
  ];
  if (terrain?.status === 'estimated_90m' && terrain.source) {
    sourceFacts.push(`지형: ${terrain.source}`);
  }
  if (sources.some((source) => /(?:^|[^a-z])(osm|osmnx|openstreetmap)/i.test(source))) {
    sourceFacts.push('보행망: OpenStreetMap contributors');
  }

  return (
    <p className="map__note" role="note">
      {route?.geometryQuality === 'mixed'
        && '실선은 주 경로, 점선은 보행 연결 구간입니다. '}
      {route?.geometryQuality === 'estimated' && '보행 연결 경로 구간입니다. '}
      {sourceFacts.join(' · ')}
    </p>
  );
}
