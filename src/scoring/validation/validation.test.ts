/**
 * 점수 검증 (기획서 §8). 단순 임의 점수가 아님을 보장한다.
 *
 * 검증 항목:
 *  1. 계단 포함 경로(R1)가 장애인 프로필에서 승강기 경로(R2)보다 낮다.
 *  2. 승강기 포함 경로(R2)가 고령자·장애인에서 일반버스(R4)보다 높다.
 *  3. 저상버스 경로(R3)가 장애인에서 일반버스(R4)보다 높다.
 *  4. 저상버스 우선 옵션 시 R3 순위가 올라간다.
 *  5. 날씨(폭염·비) 변경 시 동일 경로 점수가 낮아진다.
 *  6. 프로필별 추천 순위가 달라진다(아동은 횡단 많은 R4를 더 감점).
 *  7. lowFloorStatus 판정이 정확하다.
 *
 * `npm run validate` 또는 `npm test` 로 실행. 표는 콘솔에 출력된다.
 */
import { describe, expect, it } from 'vitest';
import { demoCandidates } from '@/data/routes';
import { WEATHER_SCENARIOS } from '@/data/weather';
import { recommendRoutes, scoreRoute } from '@/scoring/engine';
import type { ProfileId, ScoredRoute } from '@/types';

const ROUTES = demoCandidates();
const NORMAL = WEATHER_SCENARIOS.normal;

/** 모든 후보를 채점해 routeId→finalScore 맵 반환 */
function scoreAll(profile: ProfileId, weatherId: keyof typeof WEATHER_SCENARIOS, opts = {}) {
  const weather = WEATHER_SCENARIOS[weatherId];
  const fastest = Math.min(...ROUTES.map((r) => r.totalDurationMin));
  const map: Record<string, ReturnType<typeof scoreRoute>> = {};
  ROUTES.forEach((r, i) => {
    map[r.id] = scoreRoute(r, weather, profile, fastest, i + 1, opts);
  });
  return map;
}

describe('① 계단 vs 승강기 — 장애인 프로필', () => {
  it('계단(육교) 경로 R1이 승강기 경로 R2보다 낮게 평가된다', () => {
    const s = scoreAll('disabled', 'normal');
    expect(s['r2-subway'].finalScore).toBeGreaterThan(s['r1-overpass'].finalScore);
    // 승강기 하위 점수도 명확히 차이
    expect(s['r2-subway'].components.elevator).toBeGreaterThan(
      s['r1-overpass'].components.elevator,
    );
  });

  it('계단 경로 R1은 장애인 추천 상위 3개에서 제외된다', () => {
    const top3 = recommendRoutes(ROUTES, NORMAL, 'disabled');
    expect(top3.map((r) => r.route.id)).not.toContain('r1-overpass');
  });
});

describe('② 승강기 가점 — 고령자·장애인', () => {
  it.each<ProfileId>(['elderly', 'disabled'])(
    '%s 프로필에서 승강기 경로 R2가 일반버스 R4보다 높다',
    (profile) => {
      const s = scoreAll(profile, 'normal');
      expect(s['r2-subway'].finalScore).toBeGreaterThan(s['r4-regularbus'].finalScore);
    },
  );
});

describe('③ 저상버스 가점 — 장애인', () => {
  it('저상버스 R3가 일반버스 R4보다 높다', () => {
    const s = scoreAll('disabled', 'normal');
    expect(s['r3-lowfloor'].finalScore).toBeGreaterThan(s['r4-regularbus'].finalScore);
    expect(s['r3-lowfloor'].components.lowFloorBus).toBeGreaterThan(
      s['r4-regularbus'].components.lowFloorBus,
    );
  });
});

describe('④ 저상버스 우선 옵션', () => {
  it('우선 옵션이 켜지면 R3의 추천 순위가 올라간다', () => {
    const idx = (list: ScoredRoute[]) => list.findIndex((r) => r.route.id === 'r3-lowfloor');
    const off = recommendRoutes(ROUTES, NORMAL, 'general', {}, 4);
    const on = recommendRoutes(ROUTES, NORMAL, 'general', { lowFloorPriority: true }, 4);
    expect(idx(on)).toBeLessThan(idx(off));
  });
});

describe('⑤ 날씨 반영', () => {
  it('폭염 시 실외 보행이 긴 R1의 날씨 안전 점수가 낮아진다', () => {
    const normal = scoreAll('general', 'normal');
    const heat = scoreAll('general', 'heatwave');
    expect(heat['r1-overpass'].components.weatherSafety).toBeLessThan(
      normal['r1-overpass'].components.weatherSafety,
    );
    expect(heat['r1-overpass'].finalScore).toBeLessThan(normal['r1-overpass'].finalScore);
  });

  it('비 올 때 경사 구간이 있는 R3의 날씨 위험이 올라간다', () => {
    const normal = scoreAll('general', 'normal');
    const rain = scoreAll('general', 'rain');
    expect(rain['r3-lowfloor'].display.weatherRisk).toBeGreaterThan(
      normal['r3-lowfloor'].display.weatherRisk,
    );
  });

  it('미세먼지 나쁨 시 실외 이동이 긴 경로의 날씨 안전 점수가 낮아진다', () => {
    const normal = scoreAll('general', 'normal');
    const dust = scoreAll('general', 'dust');
    expect(dust['r1-overpass'].components.weatherSafety).toBeLessThan(
      normal['r1-overpass'].components.weatherSafety,
    );
  });
});

describe('⑥ 프로필별 추천 차이', () => {
  it('횡단보도·사고위험이 많은 R4는 아동 프로필에서 더 크게 감점된다', () => {
    const general = scoreAll('general', 'normal');
    const child = scoreAll('child', 'normal');
    expect(child['r4-regularbus'].finalScore).toBeLessThan(
      general['r4-regularbus'].finalScore,
    );
  });

  it('아동에서는 안전한 R3가 R4보다 높다', () => {
    const s = scoreAll('child', 'normal');
    expect(s['r3-lowfloor'].finalScore).toBeGreaterThan(s['r4-regularbus'].finalScore);
  });
});

describe('⑦ lowFloorStatus 판정', () => {
  it('R3=확정, R4=일반, R2=버스없음', () => {
    const s = scoreAll('general', 'normal');
    expect(s['r3-lowfloor'].lowFloorStatus).toBe('confirmed');
    expect(s['r4-regularbus'].lowFloorStatus).toBe('regular');
    expect(s['r2-subway'].lowFloorStatus).toBe('none');
  });
});

/* ───────── 검증 결과 표 출력 (기획서 §8: 표 형태) ───────── */
describe('검증 결과 표', () => {
  const profiles: ProfileId[] = ['general', 'elderly', 'child', 'disabled'];

  it('프로필 × 경로 최종점수 표', () => {
    const table: Record<string, Record<string, number>> = {};
    for (const p of profiles) {
      const s = scoreAll(p, 'normal');
      table[p] = {};
      for (const r of ROUTES) table[p][r.summary] = s[r.id].finalScore;
    }
    // eslint-disable-next-line no-console
    console.log('\n[표1] 프로필별 경로 최종점수 (평상 날씨)');
    console.table(table);

    const weatherTable: Record<string, Record<string, number>> = {};
    const scenarios = ['normal', 'heatwave', 'coldwave', 'rain', 'dust'] as const;
    for (const w of scenarios) {
      const s = scoreAll('general', w);
      weatherTable[WEATHER_SCENARIOS[w].label] = {};
      for (const r of ROUTES)
        weatherTable[WEATHER_SCENARIOS[w].label][r.summary] = s[r.id].display.weatherRisk;
    }
    // eslint-disable-next-line no-console
    console.log('\n[표2] 날씨 시나리오별 경로 날씨위험 점수 (일반 프로필)');
    console.table(weatherTable);

    expect(Object.keys(table)).toHaveLength(4);
  });
});
