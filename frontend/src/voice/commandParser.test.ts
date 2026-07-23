import { describe, expect, it } from 'vitest';
import { parseVoiceCommand } from './commandParser';
import type { ParsedCommand, VoiceIntent } from './intents';

const intents = (text: string): VoiceIntent[] =>
  parseVoiceCommand(text).commands.map((c) => c.intent);

function find<T extends VoiceIntent>(text: string, intent: T) {
  return parseVoiceCommand(text).commands.find((c) => c.intent === intent) as
    | Extract<ParsedCommand, { intent: T }>
    | undefined;
}

describe('음성 챗봇 파서 — 요구사항 §12 명령', () => {
  it('"서면역까지 가는 길 찾아줘" → SEARCH_DESTINATION (서면역)', () => {
    const cmd = find('서면역까지 가는 길 찾아줘', 'SEARCH_DESTINATION');
    expect(cmd).toBeTruthy();
    expect(cmd!.destination).toContain('서면역');
  });

  it('"고령자 기준으로 알려줘" → SET_PROFILE elderly', () => {
    expect(find('고령자 기준으로 알려줘', 'SET_PROFILE')?.profile).toBe('elderly');
    expect(intents('고령자 기준으로 알려줘')).not.toContain('SEARCH_DESTINATION');
  });

  it('"고령자 기준으로 찾아줘" → SET_PROFILE (목적지 오인 없음)', () => {
    expect(intents('고령자 기준으로 찾아줘')).toEqual(['SET_PROFILE']);
  });

  it('"장애인 기준으로 계단 없는 길" → SET_PROFILE disabled + avoidStairs', () => {
    const p = parseVoiceCommand('장애인 기준으로 계단 없는 길');
    expect(p.commands.find((c) => c.intent === 'SET_PROFILE')).toMatchObject({
      profile: 'disabled',
    });
    expect(p.avoidStairs).toBe(true);
    expect(p.commands.some((c) => c.intent === 'SEARCH_DESTINATION')).toBe(false);
  });

  it('청소년·임산부 발화를 각각의 프로필로 구분한다', () => {
    expect(find('청소년 기준으로 알려줘', 'SET_PROFILE')?.profile).toBe('youth');
    expect(find('임산부 기준으로 알려줘', 'SET_PROFILE')?.profile).toBe('pregnant');
  });

  it('짐·유아차·그늘·환승 최소를 이번 이동 조건으로 추출한다', () => {
    const conditions = parseVoiceCommand('짐이 많고 유아차로 그늘 많은 환승 최소 길').commands
      .filter((command) => command.intent === 'SET_TRIP_CONDITION')
      .map((command) => command.condition);
    expect(conditions).toEqual([
      'carryLuggage',
      'stroller',
      'shadePriority',
      'minimizeTransfers',
    ]);
  });

  it('"저상버스 우선으로 찾아줘" → SET_LOW_FLOOR_BUS_PRIORITY', () => {
    expect(intents('저상버스 우선으로 찾아줘')).toEqual(['SET_LOW_FLOOR_BUS_PRIORITY']);
  });

  it('"더위 피하는 길로 안내해줘" → SET_WEATHER_AVOIDANCE heat', () => {
    expect(find('더위 피하는 길로 안내해줘', 'SET_WEATHER_AVOIDANCE')?.weatherMode).toBe('heat');
  });

  it('"비 안 맞는 길로 가고 싶어" → SET_WEATHER_AVOIDANCE rain', () => {
    expect(find('비 안 맞는 길로 가고 싶어', 'SET_WEATHER_AVOIDANCE')?.weatherMode).toBe('rain');
  });

  it('"첫 번째 경로 설명해줘" → EXPLAIN_ROUTE 0', () => {
    expect(find('첫 번째 경로 설명해줘', 'EXPLAIN_ROUTE')?.routeIndex).toBe(0);
  });

  it('"두 번째 경로로 안내해줘" → SELECT_ROUTE 1', () => {
    expect(find('두 번째 경로로 안내해줘', 'SELECT_ROUTE')?.routeIndex).toBe(1);
  });

  it('"다시 말해줘" → REPEAT_GUIDE', () => {
    expect(intents('다시 말해줘')).toContain('REPEAT_GUIDE');
  });

  it('"엘리베이터 있는 길로" → elevatorPriority 플래그', () => {
    expect(parseVoiceCommand('엘리베이터 있는 길로 가줘').elevatorPriority).toBe(true);
  });

  it('인식 불가 발화 → UNKNOWN', () => {
    expect(intents('음 그러니까 어')).toEqual(['UNKNOWN']);
  });
});
