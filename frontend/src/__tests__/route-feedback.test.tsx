// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { resolveCurrentAuth, startKakaoLogin } from '@/auth/api';
import RouteFeedback from '@/components/RouteFeedback';
import { demoCandidates } from '@/data/routes';
import { WEATHER_SCENARIOS } from '@/data/weather';
import { recommendRoutes } from '@/scoring/engine';
import { useAppStore } from '@/store/appStore';

vi.mock('@/auth/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/auth/api')>();
  return {
    ...actual,
    resolveCurrentAuth: vi.fn(),
    startKakaoLogin: vi.fn(),
  };
});

const resolveCurrentAuthMock = vi.mocked(resolveCurrentAuth);

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

beforeEach(() => {
  resolveCurrentAuthMock.mockResolvedValue({
    status: 'authenticated',
    user: { id: 'mock-user', preference: {} },
  });
});

function seedSelectedRoute() {
  const recommendations = recommendRoutes(
    demoCandidates(),
    WEATHER_SCENARIOS.normal,
    'general',
  );
  const selected = {
    ...recommendations[0],
    score: {
      ...recommendations[0].score,
      feedbackToken: 'signed-feedback-token-for-ui-contract',
    },
  };
  useAppStore.setState({
    recommendations: [selected, ...recommendations.slice(1)],
    selectedRouteId: selected.route.id,
  });
  return selected;
}

describe('실제 경로 이용 후기', () => {
  it('선택형 직접 관측 3개를 camelCase 1~5 값으로 전송한다', async () => {
    seedSelectedRoute();

    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        status: 201,
        ok: true,
        json: async () => ({ id: 'impression-1' }),
      } as Response)
      .mockResolvedValueOnce({
        status: 201,
        ok: true,
        json: async () => ({ id: 'review-1' }),
      } as Response);
    vi.stubGlobal('fetch', fetchMock);

    render(<RouteFeedback />);
    const submit = await screen.findByRole('button', { name: '후기 등록' });
    fireEvent.change(screen.getByLabelText('가장 불편했던 요소'), {
      target: { value: 'crowding' },
    });
    fireEvent.change(screen.getByLabelText('혼잡으로 인한 이용 불편'), {
      target: { value: '4' },
    });
    fireEvent.change(screen.getByLabelText('환승 안내·정보 이용 불편'), {
      target: { value: '3' },
    });
    fireEvent.change(screen.getByLabelText('교통약자 시설 이용 불편'), {
      target: { value: '2' },
    });
    fireEvent.click(screen.getByRole('button', { name: '이용 가능했어요' }));
    fireEvent.click(submit);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const request = fetchMock.mock.calls[1]?.[1] as RequestInit;
    const payload = JSON.parse(String(request.body)) as Record<string, unknown>;
    expect(payload).toMatchObject({
      wasUsable: true,
      issueType: 'crowding',
      crowdingDifficulty: 4,
      transferInformationDifficulty: 3,
      accessibilityFacilityDifficulty: 2,
      trainingConsent: false,
    });
  });

  it('이용 가능 여부를 고르지 않으면 후기를 전송하지 않는다', async () => {
    seedSelectedRoute();
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    render(<RouteFeedback />);
    fireEvent.click(await screen.findByRole('button', { name: '후기 등록' }));
    expect(screen.getByRole('status').textContent).toContain('이용 가능 여부');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('인증 확인 중에는 후기 등록 버튼을 먼저 노출하지 않는다', () => {
    seedSelectedRoute();
    resolveCurrentAuthMock.mockReturnValue(new Promise(() => undefined));

    render(<RouteFeedback />);
    expect(screen.queryByRole('button', { name: '후기 등록' })).toBeNull();
    expect(screen.getByRole('status').textContent).toContain('로그인 상태');
  });

  it('비로그인에서는 활성 후기 등록 버튼이 없고 제출되지 않는다', async () => {
    seedSelectedRoute();
    resolveCurrentAuthMock.mockResolvedValue({ status: 'guest' });
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    render(<RouteFeedback />);
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: '후기 등록' })).toBeNull();
    });
    expect(screen.getByRole('button', { name: '카카오 로그인' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '카카오 로그인' }));
    expect(startKakaoLogin).toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('auth/me 확인 불가에서는 앱이 중단되지 않고 등록 버튼도 노출되지 않는다', async () => {
    seedSelectedRoute();
    resolveCurrentAuthMock.mockResolvedValue({ status: 'unavailable' });

    render(<RouteFeedback />);
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: '후기 등록' })).toBeNull();
    });
    expect(screen.getByRole('status').textContent).toContain('확인하기 어렵');
  });

  it('로그인 상태에서는 후기 폼과 등록 버튼이 표시된다', async () => {
    seedSelectedRoute();

    render(<RouteFeedback />);
    expect(await screen.findByRole('button', { name: '후기 등록' })).toBeTruthy();
    expect(screen.getByLabelText('만족도')).toBeTruthy();
    expect(screen.getByLabelText('추가 의견')).toBeTruthy();
  });

  it('후기 폼 입력 요소가 동일한 컨테이너 너비 규칙을 사용한다', async () => {
    seedSelectedRoute();
    const { container } = render(<RouteFeedback />);
    await screen.findByRole('button', { name: '후기 등록' });
    expect(container.querySelector('.route-feedback')).toBeTruthy();
    expect(container.querySelectorAll('.route-feedback select').length).toBeGreaterThan(0);
    expect(container.querySelector('.route-feedback textarea')).toBeTruthy();
    expect(container.querySelector('.route-feedback__details')).toBeTruthy();
  });
});
