import type { LatLng, Place, RouteCandidate, RouteSegment } from '@/types';
import demoJson from '@data/routes.demo.json';

/** 데모 대표 경로 후보(부산진구청 → 서면역) — 공유 데이터셋(data/routes.demo.json). */
const DEMO: RouteCandidate[] = demoJson as unknown as RouteCandidate[];

/** 구간 배열로부터 집계값을 채워 RouteCandidate 완성(합성 경로용) */
function assemble(
  id: string,
  summary: string,
  origin: string,
  destination: string,
  segments: RouteSegment[],
  path: LatLng[],
): RouteCandidate {
  const totalWalkM = segments
    .filter((s) => s.mode === 'walk')
    .reduce((a, s) => a + (s.distanceM ?? 0), 0);
  const totalDurationMin = segments.reduce(
    (a, s) => a + s.durationMin + (s.waitMin ?? 0),
    0,
  );
  // 환승 = 탑승하는 교통수단 수 - 1 (음수면 0)
  const vehicles = segments.filter(
    (s) => s.mode === 'bus' || s.mode === 'subway',
  ).length;
  const transferCount = Math.max(0, vehicles - 1);
  return {
    id,
    summary,
    origin,
    destination,
    segments,
    totalWalkM,
    totalDurationMin,
    transferCount,
    path,
  };
}

const c = (p?: Place): LatLng => ({ lat: p?.lat ?? 0, lng: p?.lng ?? 0 });

/** 데모 대표 경로(깊은 복사로 반환 — 역방향 등에서 원본 오염 방지). */
function demoCandidates(): RouteCandidate[] {
  return DEMO.map((r) => structuredClone(r));
}

export const DEMO_OD = { originId: 'gu-office', destinationId: 'seomyeon-stn' };

/* ───────── 임의 OD 합성기(데모 외 검색 대응) ───────── */

function haversineM(a: LatLng, b: LatLng): number {
  const R = 6371000;
  const dLat = ((b.lat - a.lat) * Math.PI) / 180;
  const dLng = ((b.lng - a.lng) * Math.PI) / 180;
  const lat1 = (a.lat * Math.PI) / 180;
  const lat2 = (b.lat * Math.PI) / 180;
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return Math.round(2 * R * Math.asin(Math.sqrt(h)));
}

/** 결정적 의사난수(같은 OD면 같은 결과 → 재현 가능) */
function seeded(seed: number): () => number {
  let s = seed % 2147483647;
  if (s <= 0) s += 2147483646;
  return () => (s = (s * 16807) % 2147483647) / 2147483647;
}

function synthCandidates(origin: Place, dest: Place): RouteCandidate[] {
  const dist = haversineM(origin, dest);
  const rnd = seeded(Math.round(dist + origin.lat * 1000));
  const mid = { lat: (origin.lat + dest.lat) / 2, lng: (origin.lng + dest.lng) / 2 };
  const path = [c(origin), mid, c(dest)];
  const walkMin = Math.max(1, Math.round(dist / 75)); // 약 4.5km/h

  // 후보1: 도보 위주
  const cand1 = assemble(
    'syn-walk',
    '도보 경로',
    origin.name,
    dest.name,
    [
      {
        id: 'sw1', mode: 'walk', description: `${dest.name}까지 도보`, durationMin: walkMin,
        distanceM: dist, outdoor: true, crosswalkCount: 1 + Math.round(rnd() * 3),
        hasSlope: rnd() > 0.6,
      },
    ],
    path,
  );

  // 후보2: 버스(저상 여부 난수)
  const lowFloor = rnd() > 0.5 ? true : rnd() > 0.5 ? false : undefined;
  const cand2 = assemble(
    'syn-bus',
    '버스 경로',
    origin.name,
    dest.name,
    [
      { id: 'sb-w1', mode: 'walk', description: '정류장까지 도보', durationMin: Math.max(2, Math.round(walkMin * 0.3)), distanceM: Math.round(dist * 0.25), outdoor: true, crosswalkCount: 1 },
      { id: 'sb-bus', mode: 'bus', description: '버스 승차', durationMin: Math.max(4, Math.round(walkMin * 0.5)), waitMin: 3 + Math.round(rnd() * 4), busRouteName: `${100 + Math.round(rnd() * 200)}`, isLowFloorBus: lowFloor },
      { id: 'sb-w2', mode: 'walk', description: '하차 후 도보', durationMin: Math.max(2, Math.round(walkMin * 0.25)), distanceM: Math.round(dist * 0.2), outdoor: true, crosswalkCount: 1 },
    ],
    path,
  );

  // 후보3: 지하철(승강기 여부 난수)
  const elev = rnd() > 0.4 ? true : rnd() > 0.5 ? false : undefined;
  const cand3 = assemble(
    'syn-subway',
    '지하철 경로',
    origin.name,
    dest.name,
    [
      { id: 'ss-w1', mode: 'walk', description: '역까지 도보', durationMin: Math.max(3, Math.round(walkMin * 0.35)), distanceM: Math.round(dist * 0.3), outdoor: true, crosswalkCount: 1 },
      { id: 'ss-sub', mode: 'subway', description: '지하철 승차', durationMin: Math.max(3, Math.round(walkMin * 0.4)), waitMin: 3, stationName: `${origin.name} 인근역`, hasElevator: elev, needsVerticalMove: true },
      { id: 'ss-w2', mode: 'walk', description: '하차 후 도보', durationMin: Math.max(2, Math.round(walkMin * 0.25)), distanceM: Math.round(dist * 0.2), outdoor: false, crosswalkCount: 0 },
    ],
    path,
  );

  return [cand1, cand2, cand3];
}

/**
 * OD에 맞는 경로 후보 반환.
 * 데모 OD(부산진구청→서면역)면 수동 검증된 대표 경로를, 그 외에는 합성 후보를 제공.
 */
export function getRouteCandidates(origin: Place, dest: Place): RouteCandidate[] {
  if (origin.id === DEMO_OD.originId && dest.id === DEMO_OD.destinationId) {
    return demoCandidates();
  }
  // 역방향 데모도 대표 경로 재사용
  if (origin.id === DEMO_OD.destinationId && dest.id === DEMO_OD.originId) {
    return demoCandidates().map((r) => ({
      ...r,
      origin: origin.name,
      destination: dest.name,
      path: [...(r.path ?? [])].reverse(),
    }));
  }
  return synthCandidates(origin, dest);
}

export { demoCandidates };
