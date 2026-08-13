// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/http';
import SignupConsentPage from './SignupConsentPage';

const authMocks = vi.hoisted(() => ({
  cancelSignup: vi.fn(),
  completeSignup: vi.fn(),
  resolveSignupStatus: vi.fn(),
  startKakaoLogin: vi.fn(),
}));

vi.mock('@/auth/api', () => authMocks);

describe('SignupConsentPage', () => {
  beforeEach(() => {
    authMocks.cancelSignup.mockReset();
    authMocks.completeSignup.mockReset();
    authMocks.resolveSignupStatus.mockReset();
    authMocks.startKakaoLogin.mockReset();
    authMocks.resolveSignupStatus.mockResolvedValue({ status: 'pending' });
    authMocks.completeSignup.mockResolvedValue(undefined);
    authMocks.cancelSignup.mockResolvedValue(undefined);
    vi.stubGlobal('location', {
      ...window.location,
      assign: vi.fn(),
    });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('필수 이용약관 체크와 공개 문서 링크를 제공한다', async () => {
    render(<SignupConsentPage />);

    expect(await screen.findByRole('heading', { level: 1, name: '동넷 시작하기' })).toBeTruthy();
    expect(screen.getByRole('main')).toBeTruthy();
    const checkbox = await screen.findByRole('checkbox', {
      name: /이용약관에 동의합니다/,
    });
    expect((checkbox as HTMLInputElement).checked).toBe(false);
    expect(screen.getByRole('checkbox', { name: /이용약관에 동의합니다/ })).toBeTruthy();
    const links = screen.getAllByRole('link', { name: '보기' });
    expect(links).toHaveLength(2);
    expect(links[0].getAttribute('href')).toBe('/terms');
    expect(links[1].getAttribute('href')).toBe('/privacy');
    expect(screen.queryByRole('checkbox', { name: /개인정보/ })).toBeNull();
    expect(
      (screen.getByRole('button', { name: '동의하고 시작하기' }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(document.querySelector('.signup-consent--compact')).toBeNull();
  });

  it('체크 후 제출하면 completeSignup을 호출하고 홈으로 이동한다', async () => {
    render(<SignupConsentPage />);
    const checkbox = await screen.findByRole('checkbox', {
      name: /이용약관에 동의합니다/,
    });
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByRole('button', { name: '동의하고 시작하기' }));

    await waitFor(() => {
      expect(authMocks.completeSignup).toHaveBeenCalledOnce();
    });
    expect(window.location.assign).toHaveBeenCalledWith('/');
  });

  it('API 실패 시 접근 가능한 오류를 보여 준다', async () => {
    authMocks.completeSignup.mockRejectedValue(new Error('network'));
    render(<SignupConsentPage />);
    fireEvent.click(
      await screen.findByRole('checkbox', { name: /이용약관에 동의합니다/ }),
    );
    fireEvent.click(screen.getByRole('button', { name: '동의하고 시작하기' }));

    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(window.location.assign).not.toHaveBeenCalled();
  });

  it('취소하면 cancelSignup 후 홈으로 이동한다', async () => {
    render(<SignupConsentPage />);
    fireEvent.click(await screen.findByRole('button', { name: '취소' }));

    await waitFor(() => {
      expect(authMocks.cancelSignup).toHaveBeenCalledOnce();
    });
    expect(window.location.assign).toHaveBeenCalledWith('/');
  });

  it('로딩 화면은 compact 배치를 쓴다', async () => {
    authMocks.resolveSignupStatus.mockReturnValue(new Promise(() => undefined));
    render(<SignupConsentPage />);
    expect(await screen.findByText(/가입 정보를 확인하고 있습니다/)).toBeTruthy();
    expect(document.querySelector('.signup-consent--compact')).toBeTruthy();
  });

  it('만료된 가입 상태에서는 다시 로그인 UI를 보여 준다', async () => {
    authMocks.resolveSignupStatus.mockResolvedValue({ status: 'absent' });
    render(<SignupConsentPage />);

    expect(
      await screen.findByText(/가입 정보가 만료되었습니다/),
    ).toBeTruthy();
    expect(document.querySelector('.signup-consent--compact')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '카카오 로그인 다시 하기' }));
    expect(authMocks.startKakaoLogin).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole('button', { name: '동넷으로 돌아가기' }));
    expect(window.location.assign).toHaveBeenCalledWith('/');
  });

  it('가입 상태 확인 실패는 만료가 아니라 재시도 UI를 보여 준다', async () => {
    authMocks.resolveSignupStatus.mockResolvedValue({ status: 'unavailable' });
    render(<SignupConsentPage />);

    expect(
      await screen.findByText(/가입 정보를 확인하지 못했습니다/),
    ).toBeTruthy();
    expect(screen.queryByText(/가입 정보가 만료되었습니다/)).toBeNull();
    authMocks.resolveSignupStatus.mockResolvedValue({ status: 'pending' });
    fireEvent.click(screen.getByRole('button', { name: '다시 확인' }));
    expect(await screen.findByRole('checkbox', { name: /이용약관에 동의합니다/ })).toBeTruthy();
  });

  it('complete가 410이면 만료 안내로 전환한다', async () => {
    authMocks.completeSignup.mockRejectedValue(new ApiError('expired', 410));
    render(<SignupConsentPage />);
    fireEvent.click(
      await screen.findByRole('checkbox', { name: /이용약관에 동의합니다/ }),
    );
    fireEvent.click(screen.getByRole('button', { name: '동의하고 시작하기' }));

    expect(await screen.findByText(/가입 정보가 만료되었습니다/)).toBeTruthy();
  });
});
