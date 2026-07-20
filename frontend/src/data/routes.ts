import type { Place, RouteCandidate } from '@/types';
import demoJson from '@data/routes.demo.json';

/** 사실이 고정된 회귀검증용 데모 OD. 다른 OD는 절대 합성하지 않는다. */
const DEMO: RouteCandidate[] = demoJson as unknown as RouteCandidate[];

export const DEMO_OD = { originId: 'gu-office', destinationId: 'seomyeon-stn' };

export function demoCandidates(): RouteCandidate[] {
  return DEMO.map((route) => structuredClone(route));
}

export function getRouteCandidates(origin: Place, destination: Place): RouteCandidate[] {
  if (origin.id === DEMO_OD.originId && destination.id === DEMO_OD.destinationId) {
    return demoCandidates();
  }
  if (origin.id === DEMO_OD.destinationId && destination.id === DEMO_OD.originId) {
    return demoCandidates().map((route) => ({
      ...route,
      origin: origin.name,
      destination: destination.name,
      path: [...(route.path ?? [])].reverse(),
    }));
  }
  return [];
}
