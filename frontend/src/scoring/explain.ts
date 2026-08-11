/**
 * 점수 → 사람이 읽는 추천 이유/주의사항/음성 요약 생성.
 */
import type {
  LowFloorStatus,
  RouteCandidate,
  ScoreComponents,
  WeatherCondition,
} from '@/types';
import { formatDurationMin } from '@/utils/formatDurationMin';

/** 경로의 저상버스 종합 상태 판정 */
export function deriveLowFloorStatus(r: RouteCandidate): LowFloorStatus {
  const buses = r.segments.filter((s) => s.mode === 'bus');
  if (buses.length === 0) return 'none';
  if (buses.some((s) => s.isLowFloorBus === false)) return 'regular';
  if (buses.every((s) => s.isLowFloorBus === true)) return 'confirmed';
  return 'unknown';
}

export function buildReasons(
  r: RouteCandidate,
  c: ScoreComponents,
  lowFloor: LowFloorStatus,
): string[] {
  const out: string[] = [];
  const hasVertical = r.segments.some((s) => s.needsVerticalMove);

  if (c.timeEfficiency !== undefined && c.timeEfficiency >= 90) out.push('후보 중 소요시간이 가장 짧은 편이에요.');
  if (c.walkComfort !== undefined && c.walkComfort >= 80) out.push(`도보가 ${r.totalWalkM}m로 보행 부담이 적어요.`);
  if (hasVertical && c.elevator !== undefined && c.elevator >= 90)
    out.push('승강기로 이동할 수 있어 계단을 피할 수 있어요.');
  if (lowFloor === 'confirmed') out.push('경로의 버스가 저상버스로 확인됐어요.');
  if (c.safety !== undefined && c.safety >= 85) out.push('횡단과 환승 부담이 낮은 편이에요.');
  if (c.weatherSafety !== undefined && c.weatherSafety >= 85) out.push('현재 날씨 조건에서 비교적 안전해요.');
  if (r.transferCount === 0) out.push('환승 없이 한 번에 이동해요.');

  if (out.length === 0) out.push('확인된 정보 범위에서 경로를 비교했어요.');
  return out.slice(0, 4);
}

export function buildCautions(
  r: RouteCandidate,
  c: ScoreComponents,
  lowFloor: LowFloorStatus,
  w: WeatherCondition,
): string[] {
  const out: string[] = [];

  const stairNoElev = r.segments.some(
    (s) => (s.hasStairs || s.needsVerticalMove) && s.hasElevator !== true,
  );
  if (stairNoElev && c.elevator !== undefined && c.elevator < 70)
    out.push('계단 구간이 있고 승강기가 확인되지 않았어요.');

  if (lowFloor === 'regular')
    out.push('일반버스가 포함돼 휠체어·유아차 탑승이 어려울 수 있어요.');

  // 날씨 위험 안내(기획서 §10)
  const weatherRisk = c.weatherSafety === undefined ? undefined : 100 - c.weatherSafety;
  if (weatherRisk !== undefined && weatherRisk >= 35) {
    if (w.isHeatwave) out.push('폭염 중 실외 보행이 길어요. 온열질환에 주의하세요.');
    else if (w.isColdwave) out.push('한파 중 대기시간이 길어요. 보온에 주의하세요.');
    if (w.sky === 'rain' || w.precipitationMm > 0)
      out.push('비가 와 계단·경사 구간이 미끄러울 수 있어요.');
    if (w.air === 'bad' || w.air === 'very_bad')
      out.push('미세먼지가 나쁨 단계예요. 마스크 착용을 권장해요.');
  }

  const walks = r.segments.filter((segment) => segment.mode === 'walk');
  const crosswalks = walks.length > 0
    && walks.every((segment) => segment.crosswalkCount !== undefined)
    ? walks.reduce((total, segment) => total + segment.crosswalkCount!, 0)
    : undefined;
  if (crosswalks !== undefined && crosswalks >= 4) out.push(`횡단보도가 ${crosswalks}곳 있어요. 횡단에 주의하세요.`);

  if (c.dataReliability !== undefined && c.dataReliability < 70)
    out.push('실시간 교통 환경에 따라 차이가 있을 수 있어요.');

  return out.slice(0, 4);
}

/** 음성안내용 1~2문장 요약 (기획서 §6-8, §11) */
export function buildVoiceSummary(
  r: RouteCandidate,
  rank: number,
  lowFloor: LowFloorStatus,
  topCaution?: string,
): string {
  const lf =
    lowFloor === 'confirmed'
      ? '저상버스 이용 가능'
      : lowFloor === 'regular'
        ? '일반버스 포함'
        : lowFloor === 'unknown'
          ? '대중교통 이용'
          : '버스 미이용';
  let s = `${rank}번 경로, ${r.summary}. 예상 ${formatDurationMin(r.totalDurationMin)}, 도보 ${r.totalWalkM}미터, 환승 ${r.transferCount}회. ${lf}.`;
  if (topCaution) s += ` 주의: ${topCaution}`;
  return s;
}
