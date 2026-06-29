import { describe, expect, it } from 'vitest';
import { parseCommand, type VoiceAction } from './commandParser';

const kinds = (text: string) => parseCommand(text).map((a) => a.kind);

describe('음성명령 파서 — 기획서 예시 명령', () => {
  it('"서면역까지 가는 길 찾아줘" → 목적지 검색', () => {
    const a = parseCommand('서면역까지 가는 길 찾아줘');
    const dest = a.find((x) => x.kind === 'search-destination') as Extract<
      VoiceAction,
      { kind: 'search-destination' }
    >;
    expect(dest).toBeTruthy();
    expect(dest.query).toContain('서면');
    expect(a.some((x) => x.kind === 'research')).toBe(false);
  });

  it('"고령자 기준으로 다시 찾아줘" → 프로필(고령자) + 재탐색', () => {
    const a = parseCommand('고령자 기준으로 다시 찾아줘');
    expect(a).toContainEqual({ kind: 'set-profile', profile: 'elderly' });
    expect(a.some((x) => x.kind === 'research')).toBe(true);
  });

  it('"장애인 기준으로 계단 없는 길 찾아줘" → 프로필(장애인) + 재탐색', () => {
    const a = parseCommand('장애인 기준으로 계단 없는 길 찾아줘');
    expect(a).toContainEqual({ kind: 'set-profile', profile: 'disabled' });
    expect(a.some((x) => x.kind === 'research')).toBe(true);
    // "계단 없는 길"을 목적지로 오인하지 않는다
    expect(a.some((x) => x.kind === 'search-destination')).toBe(false);
  });

  it('"저상버스 우선으로 알려줘" → 저상버스 우선', () => {
    expect(kinds('저상버스 우선으로 알려줘')).toContain('low-floor-priority');
    expect(kinds('저상버스 우선으로 알려줘')).not.toContain('search-destination');
  });

  it('"더위 피하는 길로 안내해줘" → 날씨 회피', () => {
    const k = kinds('더위 피하는 길로 안내해줘');
    expect(k).toContain('weather-avoid');
    expect(k).not.toContain('search-destination');
  });

  it('"첫 번째 경로 다시 설명해줘" → 1번 경로 설명', () => {
    expect(parseCommand('첫 번째 경로 다시 설명해줘')).toContainEqual({
      kind: 'describe-route',
      index: 0,
    });
  });

  it('"두 번째 경로로 안내 시작해줘" → 2번 경로 선택', () => {
    expect(parseCommand('두 번째 경로로 안내 시작해줘')).toContainEqual({
      kind: 'select-route',
      index: 1,
    });
  });

  it('인식 불가 발화 → unknown', () => {
    expect(kinds('음 그러니까 어')).toEqual(['unknown']);
  });
});
