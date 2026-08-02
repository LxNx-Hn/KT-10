// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { resolveCurrentAuth, startKakaoLogin } from '@/auth/api';
import FeedbackTabPanel from '@/v2/components/FeedbackTabPanel';
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
  vi.restoreAllMocks();
});

beforeEach(() => {
  const recommendations = recommendRoutes(
    demoCandidates(),
    WEATHER_SCENARIOS.normal,
    'general',
  );
  useAppStore.setState({
    recommendations,
    selectedRouteId: recommendations[0]?.route.id ?? null,
  });
});

describe('후기·신고 로그인 안내', () => {
  it('비로그인에서는 카카오 로그인 버튼을 하나만 보여준다', async () => {
    resolveCurrentAuthMock.mockResolvedValue({ status: 'guest' });

    render(<FeedbackTabPanel selectedRouteId="route-1" />);

    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: '카카오 로그인' })).toHaveLength(1);
    });
    expect(screen.getByText('후기와 신고 기능을 이용하려면 카카오 로그인이 필요해요.')).toBeTruthy();
    expect(screen.queryByText(/등록이 거절됩니다/)).toBeNull();
    expect(screen.queryByRole('button', { name: '후기 등록' })).toBeNull();
    expect(screen.queryByRole('button', { name: '신고 접수' })).toBeNull();
    expect(startKakaoLogin).not.toHaveBeenCalled();
  });

  it('로그인 후에는 후기·신고 기능을 유지한다', async () => {
    resolveCurrentAuthMock.mockResolvedValue({
      status: 'authenticated',
      user: { id: 'mock-user', preference: {} },
    });

    render(<FeedbackTabPanel selectedRouteId="route-1" />);

    expect(await screen.findByRole('button', { name: '후기 등록' })).toBeTruthy();
    expect(await screen.findByRole('button', { name: '신고 접수' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: '카카오 로그인' })).toBeNull();
  });
});
