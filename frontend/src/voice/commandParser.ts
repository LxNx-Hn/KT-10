/**
 * 음성명령 파서 (요구사항 §8). 한국어 발화를 규칙 기반으로 VoiceIntent 로 해석한다.
 * 한 발화에서 여러 의도(프로필 변경 + 저상버스 우선 등)를 추출할 수 있어 배열로 반환한다.
 *
 * 반환: { commands: ParsedCommand[], avoidStairs, elevatorPriority }
 * - 목적지 검색은 다른 명령("○○로 안내", "더위 피하는 길로" 등)을 오인하지 않도록 폴백으로만 시도한다.
 */
import type { ProfileId } from '@/types';
import type { ParsedCommand, VoiceParse, WeatherAvoidanceMode } from './intents';

const PROFILE_KEYWORDS: { re: RegExp; profile: ProfileId }[] = [
  { re: /고령자|어르신|노인/, profile: 'elderly' },
  { re: /장애인|휠체어/, profile: 'disabled' },
  { re: /아이|아동|어린이|유아/, profile: 'child' },
  { re: /일반\s*(기준|모드|으로)?/, profile: 'general' },
];

const ORDINALS: { re: RegExp; index: number }[] = [
  { re: /첫\s*번째|첫번|1\s*번|일\s*번째|하나/, index: 0 },
  { re: /두\s*번째|둘\s*째|2\s*번|이\s*번째/, index: 1 },
  { re: /세\s*번째|셋\s*째|3\s*번|삼\s*번째/, index: 2 },
];

function findOrdinal(text: string): number | null {
  for (const o of ORDINALS) if (o.re.test(text)) return o.index;
  return null;
}

function detectWeatherMode(text: string): WeatherAvoidanceMode | null {
  if (/더위|폭염|열기|땡볕/.test(text)) return 'heat';
  if (/비|우천|장마|젖/.test(text)) return 'rain';
  if (/추위|한파|칼바람/.test(text)) return 'cold';
  if (/미세먼지|먼지|황사/.test(text)) return 'dust';
  if (/날씨/.test(text)) return 'general';
  return null;
}

export function parseVoiceCommand(raw: string): VoiceParse {
  const text = raw.trim();
  const commands: ParsedCommand[] = [];
  const avoidStairs = /계단\s*(없는|없이|피|회피|안)/.test(text);
  const elevatorPriority = /승강기|엘리베이터|엘베/.test(text);

  if (!text) {
    return { commands: [{ intent: 'UNKNOWN', text: raw }], avoidStairs, elevatorPriority };
  }

  // 1) 프로필 변경
  for (const p of PROFILE_KEYWORDS) {
    if (p.re.test(text)) {
      commands.push({ intent: 'SET_PROFILE', profile: p.profile });
      break;
    }
  }

  // 2) 저상버스 우선
  if (/저상\s*버스|저상/.test(text)) commands.push({ intent: 'SET_LOW_FLOOR_BUS_PRIORITY' });

  // 3) 날씨 회피 (피하는/회피/안 맞는 등 회피 의도가 있을 때)
  const weatherMode = detectWeatherMode(text);
  if (weatherMode && /(피하|회피|안\s*맞|덜\s*맞|막아|걱정)/.test(text)) {
    commands.push({ intent: 'SET_WEATHER_AVOIDANCE', weatherMode });
  }

  // 4) 경로 설명/선택 (순서 지정 발화)
  const ord = findOrdinal(text);
  if (ord !== null) {
    if (/안내\s*시작|안내해|로\s*안내|출발|선택|시작/.test(text)) {
      commands.push({ intent: 'SELECT_ROUTE', routeIndex: ord });
    } else {
      commands.push({ intent: 'EXPLAIN_ROUTE', routeIndex: ord });
    }
  }

  // 5) 안내 반복 (순서 지정이 없을 때만)
  if (ord === null && /다시\s*(말|들려|읽어|설명|안내|얘기)|반복|한\s*번\s*더/.test(text)) {
    commands.push({ intent: 'REPEAT_GUIDE' });
  }

  // 6) 목적지/출발지 검색 — 다른 의도가 하나도 없을 때만 폴백으로 시도
  //    ("고령자 기준으로 찾아줘", "저상버스 우선으로 찾아줘"의 '찾'을 목적지로 오인 방지)
  if (commands.length === 0) {
    const origin = matchOrigin(text);
    const destination = matchDestination(text);
    if (destination) {
      commands.push(
        origin
          ? { intent: 'SEARCH_DESTINATION', destination, origin }
          : { intent: 'SEARCH_DESTINATION', destination },
      );
    }
  }

  if (commands.length === 0) commands.push({ intent: 'UNKNOWN', text: raw });
  return { commands, avoidStairs, elevatorPriority };
}

/** "○○까지 / ○○로 가는 / ○○ 가는 길" 에서 목적지 추출 */
function matchDestination(text: string): string | null {
  const m = text.match(/([가-힣A-Za-z0-9·\s]+?)(?:까지|으로|로)\s*(?:가는|가|안내|찾|길)/);
  if (!m) return null;
  const q = m[1]
    .replace(/^(저는|나는|여기서|지금|일단)\s*/, '')
    .replace(/\s+/g, ' ')
    .trim();
  return q.length >= 1 ? q : null;
}

/** "○○에서 출발 / ○○에서 ○○까지" 에서 출발지 추출 */
function matchOrigin(text: string): string | null {
  const m = text.match(/([가-힣A-Za-z0-9·]+?)에서\s*(?:출발|부터)?/);
  if (!m) return null;
  const q = m[1].trim();
  // "여기서/지금" 같은 대명사는 출발지로 보지 않음
  if (/^(여기|지금|거기|저기)$/.test(q)) return null;
  return q.length >= 1 ? q : null;
}
