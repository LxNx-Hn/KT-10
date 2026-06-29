/**
 * 실시간 음성 챗봇 상태머신 (요구사항 §4·§5·§6·§9).
 *
 * 흐름: 사용자 입력 → (STT) → 의도 분석 → 필요 시 추가 질문(프로필) →
 *       경로 조건 적용 → recalc → TTS 응답 → 대화 기록 표시.
 */
import { create } from 'zustand';
import { useAppStore } from '@/store/appStore';
import { PROFILES } from '@/config/profiles';
import { parseVoiceCommand } from '@/voice/commandParser';
import type {
  ProfileId,
} from '@/types';
import type {
  VoiceChatMessage,
  VoiceChatStatus,
  VoiceIntent,
  WeatherAvoidanceMode,
} from '@/voice/intents';
import { speak, stopSpeaking } from '@/voice/synthesis';

const ORD_WORD = ['첫 번째', '두 번째', '세 번째'];
const ordWord = (i: number) => ORD_WORD[i] ?? `${i + 1}번째`;

function profilePhrase(p: ProfileId): string {
  switch (p) {
    case 'elderly':
      return '고령자 기준으로 도보 거리가 짧고 승강기를 우선하는 경로를 추천하겠습니다.';
    case 'disabled':
      return '장애인 기준으로 계단을 피하고 승강기·저상버스를 우선하는 경로를 추천하겠습니다.';
    case 'child':
      return '아동 기준으로 안전한 횡단과 사고위험이 낮은 경로를 추천하겠습니다.';
    default:
      return '일반 기준으로 시간·보행 부담·날씨를 균형 있게 반영해 추천하겠습니다.';
  }
}

function weatherPhrase(mode: WeatherAvoidanceMode): string {
  switch (mode) {
    case 'heat':
      return '더위를 피하도록 실외 보행이 짧은 경로를 우선 추천했습니다.';
    case 'rain':
      return '강수 상황을 반영해 비를 덜 맞는 경로를 우선 추천했습니다.';
    case 'cold':
      return '한파를 반영해 바깥 대기시간이 짧은 경로를 우선 추천했습니다.';
    case 'dust':
      return '미세먼지를 반영해 실외 이동이 짧은 경로를 우선 추천했습니다.';
    default:
      return '날씨 위험을 반영해 다시 추천했습니다.';
  }
}

function newId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return `m_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

interface ChatState {
  status: VoiceChatStatus;
  messages: VoiceChatMessage[];
  interim: string; // 실시간 인식 중간 문장
  awaiting: 'profile' | null; // 추가 질문 대기
  profileConfirmed: boolean; // 대화 중 프로필 확정 여부
  lastGuide: string; // 마지막 안내(반복용)
  listenRequestId: number; // 외부(홈 마이크)에서 듣기 요청 트리거

  setStatus: (s: VoiceChatStatus) => void;
  setInterim: (t: string) => void;
  pushMessage: (role: VoiceChatMessage['role'], text: string, intent?: VoiceIntent) => void;
  requestListen: () => void;
  handleUserInput: (text: string) => Promise<void>;
  repeatLast: () => void;
  reset: () => void;
}

export const useVoiceChatStore = create<ChatState>((set, get) => ({
  status: 'idle',
  messages: [
    {
      id: 'welcome',
      role: 'system',
      text: '어디로 가시나요? 목적지를 말하거나 입력해 주세요. 예: "서면역까지 가는 길 찾아줘"',
      createdAt: new Date().toISOString(),
    },
  ],
  interim: '',
  awaiting: null,
  profileConfirmed: false,
  lastGuide: '',
  listenRequestId: 0,

  setStatus: (status) => set({ status }),
  setInterim: (interim) => set({ interim }),
  pushMessage: (role, text, intent) =>
    set((s) => ({
      messages: [
        ...s.messages,
        { id: newId(), role, text, createdAt: new Date().toISOString(), intent },
      ],
    })),
  requestListen: () => set((s) => ({ listenRequestId: s.listenRequestId + 1 })),

  repeatLast: () => {
    const g = get().lastGuide;
    const text = g || '다시 안내할 내용이 없습니다.';
    get().pushMessage('assistant', text, 'REPEAT_GUIDE');
    set({ status: 'speaking' });
    const ok = speak(text, { onEnd: () => set({ status: 'idle' }) });
    if (!ok) set({ status: 'idle' });
  },

  reset: () =>
    set({
      status: 'idle',
      interim: '',
      awaiting: null,
      profileConfirmed: false,
      lastGuide: '',
    }),

  handleUserInput: async (raw) => {
    const text = raw.trim();
    if (!text) return;
    const chat = get();
    chat.pushMessage('user', text);
    set({ status: 'thinking', interim: '' });

    /** 어시스턴트 응답 + TTS + 상태 전환 공통 처리 */
    const respond = (msg: string, intent: VoiceIntent, updateGuide = true) => {
      get().pushMessage('assistant', msg, intent);
      if (updateGuide) set({ lastGuide: msg });
      set({ status: 'speaking' });
      const ok = speak(msg, { onEnd: () => set({ status: 'idle' }) });
      if (!ok) set({ status: 'idle' });
    };

    const parse = parseVoiceCommand(text);
    const app = useAppStore.getState();

    // 계단 회피 / 승강기 우선 수식어
    if (parse.avoidStairs || parse.elevatorPriority) app.enableStairAvoidance();

    let didProfile = false;
    let didDestination = false;
    let didOption = false;
    let notFound: string | null = null;
    let explainIdx: number | null = null;
    let selectIdx: number | null = null;
    let repeat = false;
    let profileApplied: ProfileId | null = null;
    let lowFloorApplied = false;
    let weatherApplied: WeatherAvoidanceMode | null = null;

    for (const cmd of parse.commands) {
      switch (cmd.intent) {
        case 'SET_PROFILE':
          app.setProfileFromVoice(cmd.profile);
          didProfile = true;
          profileApplied = cmd.profile;
          break;
        case 'SEARCH_DESTINATION': {
          const place = await app.setDestinationFromVoice(cmd.destination);
          if (!place) notFound = cmd.destination;
          else didDestination = true;
          if (cmd.origin) await app.setOriginFromVoice(cmd.origin);
          break;
        }
        case 'SET_LOW_FLOOR_BUS_PRIORITY':
          app.enableLowFloorBusPriority();
          didOption = true;
          lowFloorApplied = true;
          break;
        case 'SET_WEATHER_AVOIDANCE':
          await app.enableWeatherAvoidance(cmd.weatherMode);
          didOption = true;
          weatherApplied = cmd.weatherMode;
          break;
        case 'EXPLAIN_ROUTE':
          explainIdx = cmd.routeIndex;
          break;
        case 'SELECT_ROUTE':
          selectIdx = cmd.routeIndex;
          break;
        case 'REPEAT_GUIDE':
          repeat = true;
          break;
        case 'UNKNOWN':
          break;
      }
    }

    // 1) 장소 미발견
    if (notFound) {
      respond(`${notFound} 장소를 찾지 못했습니다. 다른 목적지를 말씀해 주세요.`, 'UNKNOWN');
      return;
    }

    // 2) 반복
    if (repeat) {
      get().repeatLast();
      return;
    }

    // 3) 경로 설명
    if (explainIdx !== null) {
      const recs = useAppStore.getState().recommendations;
      const rec = recs[explainIdx];
      if (!rec) {
        respond(`${ordWord(explainIdx)} 경로가 아직 없습니다. 먼저 목적지를 검색해 주세요.`, 'UNKNOWN');
        return;
      }
      app.selectRoute(rec.route.id);
      const reasons = rec.score.reasons.map((r) => r.replace(/[.]\s*$/, '')).join(', ');
      const caution = rec.score.cautions[0] ? ` 주의할 점은 ${rec.score.cautions[0]}` : '';
      respond(`${ordWord(explainIdx)} 경로는 ${reasons}.${caution}`, 'EXPLAIN_ROUTE');
      return;
    }

    // 4) 경로 선택/안내 시작
    if (selectIdx !== null) {
      const recs = useAppStore.getState().recommendations;
      const rec = recs[selectIdx];
      if (!rec) {
        respond(`${ordWord(selectIdx)} 경로가 아직 없습니다. 먼저 목적지를 검색해 주세요.`, 'UNKNOWN');
        return;
      }
      app.selectRoute(rec.route.id);
      respond(`${ordWord(selectIdx)} 경로로 안내를 시작하겠습니다. ${rec.score.voiceSummary}`, 'SELECT_ROUTE');
      return;
    }

    // 5) 프로필 확정 처리
    const wasAwaiting = get().awaiting === 'profile';
    if (didProfile) set({ profileConfirmed: true, awaiting: null });

    // 6) 목적지만 들어왔고 아직 프로필 미확정 → 추가 질문
    if (didDestination && !didProfile && !get().profileConfirmed && !wasAwaiting) {
      const destName = useAppStore.getState().destination?.name ?? '목적지';
      set({ awaiting: 'profile' });
      respond(
        `${destName}까지 가는 경로를 찾겠습니다. ${PROFILES.general.label}, ${PROFILES.elderly.label}, ${PROFILES.child.label}, ${PROFILES.disabled.label} 중 어떤 기준으로 안내할까요?`,
        'SEARCH_DESTINATION',
      );
      return;
    }

    // 7) 프로필 질문 중인데 답이 안 옴 → 재질문
    if (get().awaiting === 'profile' && !didProfile && !didDestination && !didOption) {
      respond('일반, 고령자, 아동, 장애인 중 어떤 기준으로 안내할까요?', 'SET_PROFILE');
      return;
    }

    // 8) 결과 산출 (조건이 하나라도 바뀐 경우)
    if (didProfile || didDestination || didOption) {
      await app.recalculateRoutes();
      const top = useAppStore.getState().recommendations[0];
      const parts: string[] = [];
      if (profileApplied) parts.push(profilePhrase(profileApplied));
      if (lowFloorApplied) parts.push('저상버스 도착 정보를 확인해 경로를 다시 정렬했습니다.');
      if (weatherApplied) parts.push(weatherPhrase(weatherApplied));
      if (parts.length === 0 && didDestination) parts.push('경로를 찾았습니다.');
      const summary = top
        ? `추천 1순위는 ${top.score.voiceSummary}`
        : '조건에 맞는 추천 경로를 찾지 못했습니다.';
      const intent: VoiceIntent = didDestination
        ? 'SEARCH_DESTINATION'
        : profileApplied
          ? 'SET_PROFILE'
          : lowFloorApplied
            ? 'SET_LOW_FLOOR_BUS_PRIORITY'
            : 'SET_WEATHER_AVOIDANCE';
      respond(`${parts.join(' ')} ${summary}`.trim(), intent);
      return;
    }

    // 9) 해석 불가
    respond('명령을 이해하지 못했습니다. 목적지나 이동 기준을 말씀해 주세요.', 'UNKNOWN');
  },
}));

export { stopSpeaking };
