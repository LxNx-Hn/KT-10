/**
 * Demo map geometry for Map-first UI v2.
 *
 * IMPORTANT: These routes and facilities are screen-demo coordinates only.
 * They are NOT real routing / wayfinding API results.
 */

import type { ProfileId } from '@/types';

export type MapProfileId = ProfileId;

/** 좌표 순서: [longitude, latitude] */
export type LngLatTuple = [number, number];

export type DemoFacilityType =
  | 'bus_stop'
  | 'subway'
  | 'elevator'
  | 'rest_area'
  | 'safe_crossing'
  | 'school_zone'
  | 'low_floor_bus'
  | 'wheelchair_charger';

export type DemoFacility = {
  id: string;
  name: string;
  type: DemoFacilityType;
  coordinates: LngLatTuple;
  /** Always true — facilities are illustrative demo data only */
  demo: true;
};

export type DemoRoute = {
  profileId: MapProfileId;
  /** Demo path from 부산진구청 → 서면역 (not a real routing result) */
  coordinates: LngLatTuple[];
  facilities: DemoFacility[];
};

/** Fixed demo endpoints around Busanjin-gu Office → Seomyeon Station */
export const DEMO_ORIGIN: LngLatTuple = [129.0535, 35.1629]; // 부산진구청 (데모)
export const DEMO_DESTINATION: LngLatTuple = [129.0594, 35.1578]; // 서면역 (데모)

export const INITIAL_CENTER: LngLatTuple = [129.0594, 35.1578];

/**
 * Profile demo routes — plausible walking corridors between the two endpoints.
 * Coordinates are hand-authored for UI rehearsal, not pathfinding output.
 */
export const DEMO_ROUTES: Record<MapProfileId, DemoRoute> = {
  // 빠른 균형 경로 (비교적 직선에 가까운 데모)
  general: {
    profileId: 'general',
    coordinates: [
      DEMO_ORIGIN,
      [129.0546, 35.1618],
      [129.0558, 35.1606],
      [129.0572, 35.1594],
      [129.0584, 35.1584],
      DEMO_DESTINATION,
    ],
    facilities: [
      {
        id: 'general-bus',
        name: '버스정류장',
        type: 'bus_stop',
        coordinates: [129.0556, 35.1608],
        demo: true,
      },
      {
        id: 'general-subway',
        name: '지하철역',
        type: 'subway',
        coordinates: [129.0588, 35.1582],
        demo: true,
      },
    ],
  },

  // 보행 부담·계단을 줄인 우회 경로 (서쪽으로 살짝 우회하는 데모)
  elderly: {
    profileId: 'elderly',
    coordinates: [
      DEMO_ORIGIN,
      [129.0524, 35.1620],
      [129.0516, 35.1604],
      [129.0528, 35.1588],
      [129.0550, 35.1578],
      [129.0574, 35.1576],
      DEMO_DESTINATION,
    ],
    facilities: [
      {
        id: 'elderly-elevator',
        name: '승강기',
        type: 'elevator',
        coordinates: [129.0522, 35.1602],
        demo: true,
      },
      {
        id: 'elderly-rest',
        name: '쉼터',
        type: 'rest_area',
        coordinates: [129.0548, 35.1580],
        demo: true,
      },
    ],
  },

  // 안전한 횡단을 우선한 경로 (신호 횡단 지점을 지나는 데모)
  child: {
    profileId: 'child',
    coordinates: [
      DEMO_ORIGIN,
      [129.0544, 35.1622],
      [129.0556, 35.1612],
      [129.0568, 35.1600],
      [129.0578, 35.1588],
      [129.0588, 35.1580],
      DEMO_DESTINATION,
    ],
    facilities: [
      {
        id: 'child-crossing',
        name: '안전 횡단보도',
        type: 'safe_crossing',
        coordinates: [129.0558, 35.1610],
        demo: true,
      },
      {
        id: 'child-school',
        name: '스쿨존',
        type: 'school_zone',
        coordinates: [129.0576, 35.1590],
        demo: true,
      },
    ],
  },

  // 빠른 이동·단순한 환승을 표현하는 데모 경로
  youth: {
    profileId: 'youth',
    coordinates: [
      DEMO_ORIGIN,
      [129.0548, 35.1616],
      [129.0560, 35.1602],
      [129.0574, 35.1590],
      [129.0586, 35.1582],
      DEMO_DESTINATION,
    ],
    facilities: [
      {
        id: 'youth-bus',
        name: '버스정류장',
        type: 'bus_stop',
        coordinates: [129.0554, 35.1610],
        demo: true,
      },
      {
        id: 'youth-crossing',
        name: '안전 횡단보도',
        type: 'safe_crossing',
        coordinates: [129.0572, 35.1592],
        demo: true,
      },
    ],
  },

  // 승강기·저상버스를 고려한 무장애 경로 (데모)
  disabled: {
    profileId: 'disabled',
    coordinates: [
      DEMO_ORIGIN,
      [129.0538, 35.1614],
      [129.0548, 35.1600],
      [129.0562, 35.1588],
      [129.0576, 35.1582],
      [129.0586, 35.1579],
      DEMO_DESTINATION,
    ],
    facilities: [
      {
        id: 'disabled-elevator',
        name: '승강기',
        type: 'elevator',
        coordinates: [129.0546, 35.1602],
        demo: true,
      },
      {
        id: 'disabled-lowfloor',
        name: '저상버스 정류장',
        type: 'low_floor_bus',
        coordinates: [129.0564, 35.1588],
        demo: true,
      },
      {
        id: 'disabled-charger',
        name: '전동휠체어 충전소',
        type: 'wheelchair_charger',
        coordinates: [129.0582, 35.1580],
        demo: true,
      },
    ],
  },

  // 긴 도보·계단 부담을 줄이는 데모 경로
  pregnant: {
    profileId: 'pregnant',
    coordinates: [
      DEMO_ORIGIN,
      [129.0528, 35.1618],
      [129.0520, 35.1602],
      [129.0534, 35.1586],
      [129.0556, 35.1578],
      [129.0578, 35.1576],
      DEMO_DESTINATION,
    ],
    facilities: [
      {
        id: 'pregnant-elevator',
        name: '승강기',
        type: 'elevator',
        coordinates: [129.0526, 35.1600],
        demo: true,
      },
      {
        id: 'pregnant-rest',
        name: '쉼터',
        type: 'rest_area',
        coordinates: [129.0554, 35.1580],
        demo: true,
      },
    ],
  },
};

export function getDemoPath(profileId: MapProfileId, reversed: boolean): LngLatTuple[] {
  const path = DEMO_ROUTES[profileId].coordinates;
  return reversed ? [...path].reverse() : path;
}

export function getDemoEndpoints(
  reversed: boolean,
): { origin: LngLatTuple; destination: LngLatTuple } {
  return reversed
    ? { origin: DEMO_DESTINATION, destination: DEMO_ORIGIN }
    : { origin: DEMO_ORIGIN, destination: DEMO_DESTINATION };
}
