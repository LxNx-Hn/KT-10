// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import KakaoLoginButton from './KakaoLoginButton';

const authMocks = vi.hoisted(() => ({
  getCurrentUser: vi.fn(),
  logout: vi.fn(),
  startKakaoLogin: vi.fn(),
}));

vi.mock('@/auth/api', () => authMocks);

vi.mock('@/store/appStore', () => ({
  useAppStore: (selector: (state: { setProfile: (id: string) => void }) => unknown) =>
    selector({ setProfile: vi.fn() }),
}));

describe('KakaoLoginButton', () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    authMocks.getCurrentUser.mockReset();
    authMocks.logout.mockReset();
    authMocks.startKakaoLogin.mockReset();
    authMocks.getCurrentUser.mockResolvedValue(null);
  });

  it('비로그인에서 카카오 노란색 CTA를 보이고 기존 login handler를 호출한다', async () => {
    render(<KakaoLoginButton />);
    const button = await screen.findByRole('button', { name: '카카오 로그인' });
    expect(button.className).toContain('btn--kakao');
    expect(button.className).not.toContain('btn--ghost');
    fireEvent.click(button);
    expect(authMocks.startKakaoLogin).toHaveBeenCalledOnce();
  });

  it('로그인 후 로그아웃 버튼은 ghost 스타일을 유지한다', async () => {
    authMocks.getCurrentUser.mockResolvedValue({
      id: 'u1',
      nickname: '테스트',
      preference: { profile: 'general' },
    });
    render(<KakaoLoginButton />);
    const button = await screen.findByRole('button', { name: '테스트 · 로그아웃' });
    expect(button.className).toContain('btn--ghost');
    expect(button.className).not.toContain('btn--kakao');
  });

  it('로그아웃 중 disabled 상태를 유지한다', async () => {
    authMocks.getCurrentUser.mockResolvedValue({
      id: 'u1',
      nickname: '테스트',
      preference: { profile: 'general' },
    });
    let resolveLogout: (() => void) | undefined;
    authMocks.logout.mockImplementation(
      () => new Promise<void>((resolve) => {
        resolveLogout = resolve;
      }),
    );
    render(<KakaoLoginButton />);
    const button = await screen.findByRole('button', { name: '테스트 · 로그아웃' });
    fireEvent.click(button);
    expect(
      (screen.getByRole('button', { name: '로그아웃 중…' }) as HTMLButtonElement).disabled,
    ).toBe(true);
    resolveLogout?.();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '카카오 로그인' })).toBeTruthy();
    });
  });
});
