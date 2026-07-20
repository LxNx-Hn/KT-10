import { useEffect, useMemo, useRef, useState } from 'react';
import { useAppStore } from '@/store/appStore';
import { DISTRICT } from '@/config/district';
import { hasKakaoKey, loadKakaoMaps } from '@/map/kakaoLoader';
import type { LatLng } from '@/types';

/** 좌표 배열 → SVG 좌표로 정규화(폴백 스키매틱용) */
function project(points: LatLng[], w: number, h: number, pad = 24) {
  if (points.length === 0) return [];
  const lats = points.map((p) => p.lat);
  const lngs = points.map((p) => p.lng);
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

  const origin = useAppStore((s) => s.origin);
  const destination = useAppStore((s) => s.destination);
  const recommendations = useAppStore((s) => s.recommendations);
  const selectedRouteId = useAppStore((s) => s.selectedRouteId);
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
      })
      .catch(() => setFallback(true));
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
      const info = new kakao.maps.InfoWindow({
        content: `<div style="padding:4px 8px">${escapeHtml(label)}</div>`,
      });
      info.open(map, marker);
      overlaysRef.current.push(marker, info);
    };
    if (origin) addMarker(origin, `출발: ${origin.name}`);
    if (destination) addMarker(destination, `도착: ${destination.name}`);

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
        line.setMap(map);
        overlaysRef.current.push(line);
      }
      const bounds = new kakao.maps.LatLngBounds();
      selectedPath.forEach((p) => bounds.extend(new kakao.maps.LatLng(p.lat, p.lng)));
      map.setBounds(bounds);
    }
  }, [origin, destination, selectedPath, selectedRoute]);

  if (!fallback) {
    return (
      <div className="map" role="region" aria-label="지도">
        <div ref={containerRef} className="map__canvas" />
        <MapDataNotice quality={selectedRoute?.geometryQuality} sources={selectedRoute?.sources} />
      </div>
    );
  }

  // ── 폴백 스키매틱(Kakao 키 없을 때) ──
  const W = 600;
  const H = 280;
  const pts = project(selectedPath, W, H);
  return (
    <div className="map" role="region" aria-label="경로 약도(데모)">
      <div className="map__fallback">
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" height="100%" aria-hidden="true">
          <rect x="0" y="0" width={W} height={H} fill="#eef2f7" rx="12" />
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
          데모 약도 · 실제 Kakao 지도는 <code>.env</code> 에 <code>VITE_KAKAO_MAP_KEY</code> 설정 시 표시됩니다.
        </p>
        <MapDataNotice quality={selectedRoute?.geometryQuality} sources={selectedRoute?.sources} />
      </div>
    </div>
  );
}

function MapDataNotice({ quality, sources = [] }: { quality?: 'exact' | 'mixed' | 'estimated'; sources?: string[] }) {
  return (
    <p className="map__note" role="note">
      {quality === 'mixed' && '실선은 확인된 geometry, 점선은 상세 보행 geometry 미확인 구간입니다. '}
      {quality === 'estimated' && '이 경로 geometry는 추정값입니다. '}
      경로: {sources.length ? sources.join(' · ') : '데모 데이터'} · 지도: Kakao Maps · 지형: Copernicus DEM/Open-Meteo · 보행망: OpenStreetMap contributors
    </p>
  );
}
