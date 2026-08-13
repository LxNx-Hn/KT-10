// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/http';
import AccountDeletionPage from './AccountDeletionPage';

const authMocks = vi.hoisted(() => ({
  cancelExternalAccountDeletion: vi.fn(),
  confirmExternalAccountDeletion: vi.fn(),
  resolveAccountDeletionStatus: vi.fn(),
  resolveDeletionPageAuth: vi.fn(),
  startAccountDeletionVerification: vi.fn(),
  withdraw: vi.fn(),
}));

vi.mock('@/auth/api', () => authMocks);

describe('AccountDeletionPage', () => {
  beforeEach(() => {
    authMocks.cancelExternalAccountDeletion.mockReset();
    authMocks.confirmExternalAccountDeletion.mockReset();
    authMocks.resolveAccountDeletionStatus.mockReset();
    authMocks.resolveDeletionPageAuth.mockReset();
    authMocks.startAccountDeletionVerification.mockReset();
    authMocks.withdraw.mockReset();
    authMocks.resolveDeletionPageAuth.mockResolvedValue({ status: 'guest' });
    authMocks.resolveAccountDeletionStatus.mockResolvedValue({ status: 'absent' });
    authMocks.confirmExternalAccountDeletion.mockResolvedValue(undefined);
    authMocks.cancelExternalAccountDeletion.mockResolvedValue(undefined);
    authMocks.withdraw.mockResolvedValue(undefined);
    window.history.pushState({}, '', '/account-deletion');
    vi.stubGlobal('location', {
      ...window.location,
      assign: vi.fn(),
      search: '',
    });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.pushState({}, '', '/');
  });

  it('게스트에게 카카오 본인 확인 CTA를 보여 주고 가입 체크박스는 없다', async () => {
    render(<AccountDeletionPage />);
    expect(await screen.findByRole('heading', { level: 1, name: '동넷 계정 삭제' })).toBeTruthy();
    expect(screen.getByRole('main')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '카카오로 본인 확인' }));
    expect(authMocks.startAccountDeletionVerification).toHaveBeenCalledOnce();
    expect(screen.queryByRole('checkbox')).toBeNull();
    expect(screen.queryByText(/123456|kakao_id|user_id/i)).toBeNull();
  });

  it('authenticated 사용자는 안내 후 withdraw를 호출한다', async () => {
    authMocks.resolveDeletionPageAuth.mockResolvedValue({
      status: 'authenticated',
      user: { id: 'u1', isAdmin: false, preference: {} },
    });
    render(<AccountDeletionPage />);
    expect(await screen.findByRole('button', { name: '탈퇴하기' })).toBeTruthy();
    expect(screen.getByText(/탈퇴하면 계정·프로필·이동 기록/)).toBeTruthy();
    expect(screen.queryByRole('checkbox')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '탈퇴하기' }));
    await waitFor(() => {
      expect(authMocks.withdraw).toHaveBeenCalledOnce();
    });
    expect(authMocks.confirmExternalAccountDeletion).not.toHaveBeenCalled();
    expect(await screen.findByText('회원 탈퇴가 완료되었습니다.')).toBeTruthy();
  });

  it('deletion verified 사용자는 외부 confirm API를 사용한다', async () => {
    authMocks.resolveAccountDeletionStatus.mockResolvedValue({ status: 'verified' });
    render(<AccountDeletionPage />);
    fireEvent.click(await screen.findByRole('button', { name: '탈퇴하기' }));
    await waitFor(() => {
      expect(authMocks.confirmExternalAccountDeletion).toHaveBeenCalledOnce();
    });
    expect(authMocks.withdraw).not.toHaveBeenCalled();
  });

  it('not-found query는 가입 버튼 없이 안내한다', async () => {
    vi.stubGlobal('location', {
      ...window.location,
      assign: vi.fn(),
      search: '?result=not-found',
    });
    render(<AccountDeletionPage />);
    expect(
      await screen.findByText('삭제할 동넷 계정을 찾을 수 없습니다.'),
    ).toBeTruthy();
    expect(screen.queryByRole('button', { name: '카카오로 본인 확인' })).toBeNull();
    expect(screen.queryByRole('button', { name: /가입/ })).toBeNull();
  });

  it('authenticated면 not-found query를 무시하고 확인 화면을 보여 준다', async () => {
    vi.stubGlobal('location', {
      ...window.location,
      assign: vi.fn(),
      search: '?result=not-found',
    });
    authMocks.resolveDeletionPageAuth.mockResolvedValue({
      status: 'authenticated',
      user: { id: 'u1', isAdmin: false, preference: {} },
    });
    render(<AccountDeletionPage />);
    expect(await screen.findByRole('button', { name: '탈퇴하기' })).toBeTruthy();
    expect(screen.queryByText('삭제할 동넷 계정을 찾을 수 없습니다.')).toBeNull();
  });

  it('unavailable은 만료가 아니라 재시도 UI를 보여 준다', async () => {
    authMocks.resolveAccountDeletionStatus.mockResolvedValue({ status: 'unavailable' });
    render(<AccountDeletionPage />);
    expect(
      await screen.findByText(/계정 삭제 상태를 확인하지 못했습니다/),
    ).toBeTruthy();
    expect(screen.queryByText(/본인 확인 정보가 만료되었습니다/)).toBeNull();
    authMocks.resolveAccountDeletionStatus.mockResolvedValue({ status: 'absent' });
    fireEvent.click(screen.getByRole('button', { name: '다시 확인' }));
    expect(await screen.findByRole('button', { name: '카카오로 본인 확인' })).toBeTruthy();
  });

  it('confirm 410은 만료 안내로 전환한다', async () => {
    authMocks.resolveAccountDeletionStatus.mockResolvedValue({ status: 'verified' });
    authMocks.confirmExternalAccountDeletion.mockRejectedValue(
      new ApiError('expired', 410),
    );
    render(<AccountDeletionPage />);
    fireEvent.click(await screen.findByRole('button', { name: '탈퇴하기' }));
    expect(
      await screen.findByText(/본인 확인 정보가 만료되었습니다/),
    ).toBeTruthy();
  });

  it('admin 409는 관리자 탈퇴 불가 오류를 보여 준다', async () => {
    authMocks.resolveDeletionPageAuth.mockResolvedValue({
      status: 'authenticated',
      user: { id: 'admin', isAdmin: true, preference: {} },
    });
    authMocks.withdraw.mockRejectedValue(new ApiError('admin', 409));
    render(<AccountDeletionPage />);
    fireEvent.click(await screen.findByRole('button', { name: '탈퇴하기' }));
    expect(
      await screen.findByRole('alert'),
    ).toBeTruthy();
    expect(screen.getByText(/관리자 계정은 탈퇴할 수 없습니다/)).toBeTruthy();
    expect(screen.queryByText('회원 탈퇴가 완료되었습니다.')).toBeNull();
  });

  it('authenticated와 verified가 동시에 있으면 삭제를 막는다', async () => {
    authMocks.resolveDeletionPageAuth.mockResolvedValue({
      status: 'authenticated',
      user: { id: 'u1', isAdmin: false, preference: {} },
    });
    authMocks.resolveAccountDeletionStatus.mockResolvedValue({ status: 'verified' });
    render(<AccountDeletionPage />);
    expect(
      await screen.findByText(/본인 확인 상태가 변경되었습니다/),
    ).toBeTruthy();
    expect(screen.getByText(/안전을 위해 계정 삭제를 다시 시작해 주세요/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: '탈퇴하기' })).toBeNull();
    expect(authMocks.withdraw).not.toHaveBeenCalled();
    expect(authMocks.confirmExternalAccountDeletion).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '동넷으로 돌아가기' }));
    expect(window.location.assign).toHaveBeenCalledWith('/');
    expect(authMocks.cancelExternalAccountDeletion).not.toHaveBeenCalled();
  });

  it('verified 취소는 deletion cancel API를 호출한다', async () => {
    authMocks.resolveAccountDeletionStatus.mockResolvedValue({ status: 'verified' });
    render(<AccountDeletionPage />);
    fireEvent.click(await screen.findByRole('button', { name: '동넷으로 돌아가기' }));
    await waitFor(() => {
      expect(authMocks.cancelExternalAccountDeletion).toHaveBeenCalledOnce();
    });
    expect(window.location.assign).toHaveBeenCalledWith('/');
  });
});
