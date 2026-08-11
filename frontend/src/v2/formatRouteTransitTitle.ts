import type { V2TransitStep } from './routeViewModel';

/**
 * 결과 sheet 상단 · RouteSummaryCard 공통 경로 표시 제목.
 * route.summary 원문을 쓰지 않고 transitSteps만 사용한다.
 * API에 없는 노선명/버스번호는 추측하지 않는다.
 */
export function formatRouteTransitTitle(
  steps: V2TransitStep[],
  fallbackSummary: string,
): string {
  const primary = steps.filter(
    (step) => step.mode === 'bus' || step.mode === 'subway',
  );
  if (primary.length === 0) {
    if (steps.some((step) => step.mode === 'walk')) return '도보';
    if (steps.some((step) => step.mode === 'transfer')) return '환승';
    return fallbackSummary.trim() || '경로';
  }

  const parts = primary.map((step) => {
    if (step.routeLabel) return `${step.modeLabel} ${step.routeLabel}`;
    return step.modeLabel;
  });

  const unique: string[] = [];
  for (const part of parts) {
    if (unique[unique.length - 1] !== part) unique.push(part);
  }
  return unique.join(' · ');
}

/** @deprecated 동일 규칙 — formatRouteTransitTitle 별칭 */
export const formatRouteCardTitle = formatRouteTransitTitle;
