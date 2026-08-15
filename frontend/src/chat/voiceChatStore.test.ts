// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { adapters } from '@/adapters';
import { demoCandidates } from '@/data/routes';
import { WEATHER_SCENARIOS } from '@/data/weather';
import { recommendRoutes } from '@/scoring/engine';
import { useAppStore } from '@/store/appStore';
import { serverRankedRecommendations } from '@/utils/routes';
import { useVoiceChatStore } from './voiceChatStore';

vi.mock('@/voice/synthesis', () => ({
  speak: vi.fn(() => false),
  stopSpeaking: vi.fn(),
}));

beforeEach(() => {
  const recommendations = recommendRoutes(
    demoCandidates(),
    WEATHER_SCENARIOS.normal,
    'general',
  );
  useAppStore.setState({
    recommendations: [...recommendations].reverse(),
    candidates: recommendations.map(({ route }) => route),
    selectedRouteId: recommendations[0]?.route.id ?? null,
    loading: false,
    error: null,
  });
  useVoiceChatStore.setState({
    status: 'idle',
    messages: [],
    interim: '',
    awaiting: null,
    profileConfirmed: true,
    lastGuide: '',
    listenRequestId: 0,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('음성 챗봇 결과 계약', () => {
  it('화면과 같은 점수순 두 번째 경로를 선택하며 턴바이턴 시작으로 과장하지 않는다', async () => {
    const ranked = serverRankedRecommendations(useAppStore.getState().recommendations);

    await useVoiceChatStore.getState().handleUserInput('두 번째 경로로 안내해줘');

    expect(useAppStore.getState().selectedRouteId).toBe(ranked[1].route.id);
    const messages = useVoiceChatStore.getState().messages;
    const reply = messages[messages.length - 1]?.text ?? '';
    expect(reply).toContain('두 번째 경로를 선택했습니다');
    expect(reply).not.toContain('안내를 시작');
  });

  it('장소 공급자 오류를 처리하고 분석 중 상태에 멈추지 않는다', async () => {
    vi.spyOn(adapters.places, 'searchPlaces').mockRejectedValue(new Error('provider down'));

    await useVoiceChatStore.getState().handleUserInput('부산역까지 가는 길 찾아줘');

    const state = useVoiceChatStore.getState();
    expect(state.status).toBe('idle');
    expect(state.messages[state.messages.length - 1]?.text).toContain('다시 시도');
  });

  it('경로 설명은 routeSetToken으로 NIM 설명을 먼저 요청한다', async () => {
    const ranked = serverRankedRecommendations(useAppStore.getState().recommendations);
    const routeSetToken = 'route-set-token-1234567890';
    const recommendations = ranked.map((item, index) => index === 0
      ? {
          ...item,
          routeSetToken,
          score: {
            ...item.score,
            voiceSummary: '규칙 기반 안내입니다.',
            reasons: ['규칙 기반 근거입니다.'],
          },
        }
      : item);
    vi.spyOn(adapters.routes, 'explainRoute').mockResolvedValue({
      routeId: recommendations[0].route.id,
      explanation: 'NIM 경로 설명입니다.',
      provider: 'nvidia_nim',
    });
    useAppStore.setState({ recommendations });

    await useVoiceChatStore.getState().handleUserInput('첫 번째 경로 설명');

    expect(adapters.routes.explainRoute).toHaveBeenCalledWith(
      routeSetToken,
      recommendations[0].route.id,
    );
    const messages = useVoiceChatStore.getState().messages;
    const reply = messages[messages.length - 1]?.text ?? '';
    expect(reply).toContain('NIM 경로 설명입니다.');
    expect(reply).not.toContain('규칙 기반 안내입니다.');
    expect(reply).not.toContain('규칙 기반 근거입니다.');
    expect(reply).not.toContain('..');
  });

  it('NIM 설명 호출이 실패하면 기존 voiceSummary로 설명한다', async () => {
    const ranked = serverRankedRecommendations(useAppStore.getState().recommendations);
    const recommendations = ranked.map((item, index) => index === 0
      ? {
          ...item,
          routeSetToken: 'route-set-token-1234567890',
          score: {
            ...item.score,
            voiceSummary: '규칙 기반 안내입니다.',
            reasons: ['규칙 기반 근거입니다.'],
          },
        }
      : item);
    vi.spyOn(adapters.routes, 'explainRoute').mockRejectedValue(new Error('NIM down'));
    useAppStore.setState({ recommendations });

    await useVoiceChatStore.getState().handleUserInput('첫 번째 경로 설명');

    const messages = useVoiceChatStore.getState().messages;
    const reply = messages[messages.length - 1]?.text ?? '';
    expect(reply).toContain('규칙 기반 안내입니다.');
    expect(reply).not.toContain('요청을 처리하지 못했습니다');
  });

  it('routeSetToken이 없으면 NIM 호출 없이 기존 설명을 사용한다', async () => {
    const ranked = serverRankedRecommendations(useAppStore.getState().recommendations);
    ranked[0].score.voiceSummary = '규칙 기반 안내입니다.';
    ranked[0].score.reasons = ['규칙 기반 근거입니다.'];
    vi.spyOn(adapters.routes, 'explainRoute');
    useAppStore.setState({ recommendations: ranked });

    await useVoiceChatStore.getState().handleUserInput('첫 번째 경로 설명');

    expect(adapters.routes.explainRoute).not.toHaveBeenCalled();
    const messages = useVoiceChatStore.getState().messages;
    const reply = messages[messages.length - 1]?.text ?? '';
    expect(reply).toContain('규칙 기반 안내입니다.');
    expect(reply).not.toContain('규칙 기반 근거입니다.');
    expect(reply).not.toContain('..');
  });

  it('휠체어 발화는 기존 route-set을 버리고 세션 휠체어 검색을 수행한다', async () => {
    const search = vi.spyOn(useAppStore.getState(), 'search');

    await useVoiceChatStore.getState().handleUserInput('휠체어로 갈 수 있는 길');

    const state = useAppStore.getState();
    expect(state.profile).toBe('disabled');
    expect(state.options.usesWheelchair).toBe(true);
    expect(state.options.avoidStairs).toBe(true);
    expect(state.recommendations).toEqual([]);
    expect(search).toHaveBeenCalled();
  });
});
