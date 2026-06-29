/**
 * 음성명령 파서(기획서 §11). 한국어 발화를 규칙 기반으로 해석한다.
 * 하나의 발화에서 여러 의도(프로필 변경 + 재탐색 등)를 추출할 수 있어 배열로 반환한다.
 *
 * 우선순위: 프로필 → 저상버스 → 날씨 → 경로지정(순서) → (그 외일 때만)목적지검색 → 재탐색.
 * 다른 의도가 잡히면 "○○로 안내" 류를 목적지로 오인하지 않도록 목적지검색은 폴백으로만 둔다.
 */
import type { ProfileId } from '@/types';

export type VoiceAction =
  | { kind: 'search-destination'; query: string } // 목적지 검색(+자동 탐색)
  | { kind: 'set-profile'; profile: ProfileId } // 프로필 변경
  | { kind: 'low-floor-priority' } // 저상버스 우선
  | { kind: 'weather-avoid' } // 날씨 회피
  | { kind: 'describe-route'; index: number } // n번째 경로 설명
  | { kind: 'select-route'; index: number } // n번째 경로 선택/안내 시작
  | { kind: 'repeat' } // 안내 반복
  | { kind: 'research' } // 현재 조건으로 재탐색
  | { kind: 'unknown'; text: string };

const PROFILE_KEYWORDS: { re: RegExp; profile: ProfileId }[] = [
  { re: /고령자|어르신|노인/, profile: 'elderly' },
  { re: /장애인|휠체어|계단\s*없는/, profile: 'disabled' },
  { re: /아이|아동|어린이|유아/, profile: 'child' },
  { re: /일반\s*(기준|모드|으로)?/, profile: 'general' },
];

const ORDINALS: { re: RegExp; index: number }[] = [
  { re: /첫\s*번째|첫번|1\s*번|일\s*번째/, index: 0 },
  { re: /두\s*번째|둘\s*째|2\s*번|이\s*번째/, index: 1 },
  { re: /세\s*번째|셋\s*째|3\s*번|삼\s*번째/, index: 2 },
];

function findOrdinal(text: string): number | null {
  for (const o of ORDINALS) if (o.re.test(text)) return o.index;
  return null;
}

export function parseCommand(raw: string): VoiceAction[] {
  const text = raw.trim();
  if (!text) return [{ kind: 'unknown', text: raw }];
  const actions: VoiceAction[] = [];

  // 1) 프로필 변경
  for (const p of PROFILE_KEYWORDS) {
    if (p.re.test(text)) {
      actions.push({ kind: 'set-profile', profile: p.profile });
      break;
    }
  }

  // 2) 저상버스 우선
  if (/저상\s*버스|저상/.test(text)) actions.push({ kind: 'low-floor-priority' });

  // 3) 날씨 회피
  if (/더위|폭염|비\s*피|한파|추위|날씨\s*피|미세먼지|먼지\s*피/.test(text)) {
    actions.push({ kind: 'weather-avoid' });
  }

  // 4) 경로 설명/선택 (순서 지정 발화)
  const ord = findOrdinal(text);
  if (ord !== null) {
    if (/안내\s*시작|안내해|로\s*안내|출발/.test(text)) {
      actions.push({ kind: 'select-route', index: ord });
    } else {
      actions.push({ kind: 'describe-route', index: ord });
    }
  }

  // 5) 반복 (순서 지정이 없을 때만)
  if (ord === null && /다시\s*(들려|읽어|설명|안내)|반복|한\s*번\s*더/.test(text)) {
    actions.push({ kind: 'repeat' });
  }

  // 6) 목적지 검색 — 다른 의도가 전혀 없을 때만 폴백으로 시도
  const hasIntent = actions.some((a) => a.kind !== 'unknown');
  if (!hasIntent) {
    const m = text.match(
      /(.+?)(?:까지|으로|로)\s*(?:가는|가|안내|찾|길)/,
    );
    if (m) {
      const q = m[1].replace(/^(저는|나는|여기서|지금)\s*/, '').trim();
      if (q.length >= 1) actions.push({ kind: 'search-destination', query: q });
    }
  }

  // 7) 재탐색 — 목적지 검색이 아닌 "찾아/탐색/검색" 발화
  const hasDestSearch = actions.some((a) => a.kind === 'search-destination');
  if (!hasDestSearch && /찾아|탐색|검색|다시\s*찾/.test(text)) {
    actions.push({ kind: 'research' });
  }

  if (actions.length === 0) actions.push({ kind: 'unknown', text: raw });
  return actions;
}
