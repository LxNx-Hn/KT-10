// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AccountWithdrawal from './AccountWithdrawal';

const authMocks = vi.hoisted(() => ({
  getCurrentUser: vi.fn(),
  withdraw: vi.fn(),
  notifyAuthSessionEnded: vi.fn(),
}));

vi.mock('@/auth/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/auth/api')>();
  return {
    ...actual,
    getCurrentUser: authMocks.getCurrentUser,
    withdraw: authMocks.withdraw,
    notifyAuthSessionEnded: authMocks.notifyAuthSessionEnded,
  };
});

describe('AccountWithdrawal', () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    authMocks.getCurrentUser.mockReset();
    authMocks.withdraw.mockReset();
    authMocks.notifyAuthSessionEnded.mockReset();
    authMocks.getCurrentUser.mockResolvedValue(null);
  });

  it('비로그인 사용자에게는 회원 탈퇴 버튼이 보이지 않는다', async () => {
    render(<AccountWithdrawal />);
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: '회원 탈퇴' })).toBeNull();
    });
    expect(authMocks.withdraw).not.toHaveBeenCalled();
  });

  it('로그인 사용자에게 회원 탈퇴 버튼을 노출한다', async () => {
    authMocks.getCurrentUser.mockResolvedValue({
      id: 'u1',
      nickname: '테스트',
      isAdmin: false,
      preference: {},
    });
    render(<AccountWithdrawal />);
    expect(await screen.findByRole('button', { name: '회원 탈퇴' })).toBeTruthy();
  });

  it('첫 클릭 시 확인 dialog를 열고 withdraw API를 호출하지 않는다', async () => {
    authMocks.getCurrentUser.mockResolvedValue({
      id: 'u1',
      isAdmin: false,
      preference: {},
    });
    render(<AccountWithdrawal />);
    fireEvent.click(await screen.findByRole('button', { name: '회원 탈퇴' }));
    expect(screen.getByRole('dialog', { name: '회원 탈퇴' })).toBeTruthy();
    expect(
      screen.getByText(
        '탈퇴하면 계정·프로필·이동 기록과 작성한 후기가 즉시 삭제됩니다.',
      ),
    ).toBeTruthy();
    expect(
      screen.getByText(
        '탈퇴 후에는 복구할 수 없으며, 다시 이용하려면 새 계정으로 가입해야 합니다.',
      ),
    ).toBeTruthy();
    expect(
      screen.queryByText('30일 이내 다시 로그인하면 탈퇴 신청이 철회됩니다.'),
    ).toBeNull();
    expect(authMocks.withdraw).not.toHaveBeenCalled();
  });

  it('취소하면 dialog가 닫히고 API를 호출하지 않는다', async () => {
    authMocks.getCurrentUser.mockResolvedValue({
      id: 'u1',
      isAdmin: false,
      preference: {},
    });
    render(<AccountWithdrawal />);
    fireEvent.click(await screen.findByRole('button', { name: '회원 탈퇴' }));
    fireEvent.click(screen.getByRole('button', { name: '취소' }));
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: '회원 탈퇴' })).toBeNull();
    });
    expect(authMocks.withdraw).not.toHaveBeenCalled();
  });

  it('탈퇴하기 시 withdraw를 한 번 호출하고 처리 중 중복 요청을 막는다', async () => {
    authMocks.getCurrentUser.mockResolvedValue({
      id: 'u1',
      isAdmin: false,
      preference: {},
    });
    let resolveWithdraw: (() => void) | undefined;
    authMocks.withdraw.mockImplementation(
      () => new Promise<void>((resolve) => {
        resolveWithdraw = resolve;
      }),
    );
    render(<AccountWithdrawal />);
    fireEvent.click(await screen.findByRole('button', { name: '회원 탈퇴' }));
    fireEvent.click(screen.getByRole('button', { name: '탈퇴하기' }));
    expect(screen.getByRole('button', { name: '탈퇴 처리 중…' })).toBeTruthy();
    expect((screen.getByRole('button', { name: '탈퇴 처리 중…' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: '탈퇴 처리 중…' }));
    expect(authMocks.withdraw).toHaveBeenCalledTimes(1);
    resolveWithdraw?.();
    await waitFor(() => {
      expect(authMocks.notifyAuthSessionEnded).toHaveBeenCalledOnce();
    });
  });

  it('204 성공 시 완료 안내를 표시하고 인증 UI를 게스트로 맞춘다', async () => {
    authMocks.getCurrentUser.mockResolvedValue({
      id: 'u1',
      isAdmin: false,
      preference: {},
    });
    authMocks.withdraw.mockResolvedValue(undefined);
    render(<AccountWithdrawal />);
    fireEvent.click(await screen.findByRole('button', { name: '회원 탈퇴' }));
    fireEvent.click(screen.getByRole('button', { name: '탈퇴하기' }));
    await waitFor(() => {
      expect(screen.getByText('회원 탈퇴가 완료되었습니다.')).toBeTruthy();
    });
    expect(authMocks.notifyAuthSessionEnded).toHaveBeenCalledOnce();
    expect(screen.queryByRole('button', { name: '회원 탈퇴' })).toBeNull();
  });

  it('401이면 세션 만료 안내 후 게스트 상태로 복귀한다', async () => {
    authMocks.getCurrentUser.mockResolvedValue({
      id: 'u1',
      isAdmin: false,
      preference: {},
    });
    const { ApiError } = await import('@/api/http');
    authMocks.withdraw.mockRejectedValue(new ApiError('withdraw failed', 401));
    render(<AccountWithdrawal />);
    fireEvent.click(await screen.findByRole('button', { name: '회원 탈퇴' }));
    fireEvent.click(screen.getByRole('button', { name: '탈퇴하기' }));
    await waitFor(() => {
      expect(
        screen.getByText('로그인 정보가 만료되었습니다. 다시 로그인해 주세요.'),
      ).toBeTruthy();
    });
    expect(authMocks.notifyAuthSessionEnded).toHaveBeenCalledOnce();
    expect(screen.queryByRole('button', { name: '회원 탈퇴' })).toBeNull();
  });

  it('409이면 관리자 탈퇴 불가 안내를 표시한다', async () => {
    authMocks.getCurrentUser.mockResolvedValue({
      id: 'admin',
      isAdmin: true,
      preference: {},
    });
    const { ApiError } = await import('@/api/http');
    authMocks.withdraw.mockRejectedValue(new ApiError('withdraw failed', 409));
    render(<AccountWithdrawal />);
    fireEvent.click(await screen.findByRole('button', { name: '회원 탈퇴' }));
    fireEvent.click(screen.getByRole('button', { name: '탈퇴하기' }));
    await waitFor(() => {
      expect(
        screen.getByText(
          '관리자 계정은 탈퇴할 수 없습니다. 관리자 권한을 해제한 뒤 다시 시도해 주세요.',
        ),
      ).toBeTruthy();
    });
    expect(screen.getByRole('dialog', { name: '회원 탈퇴' })).toBeTruthy();
    expect(authMocks.notifyAuthSessionEnded).not.toHaveBeenCalled();
  });

  it('기타 오류면 실패 안내를 표시하고 재시도할 수 있다', async () => {
    authMocks.getCurrentUser.mockResolvedValue({
      id: 'u1',
      isAdmin: false,
      preference: {},
    });
    authMocks.withdraw.mockRejectedValue(new Error('network'));
    render(<AccountWithdrawal />);
    fireEvent.click(await screen.findByRole('button', { name: '회원 탈퇴' }));
    fireEvent.click(screen.getByRole('button', { name: '탈퇴하기' }));
    await waitFor(() => {
      expect(
        screen.getByText('회원 탈퇴를 완료하지 못했습니다. 다시 시도해 주세요.'),
      ).toBeTruthy();
    });
    authMocks.withdraw.mockResolvedValue(undefined);
    fireEvent.click(screen.getByRole('button', { name: '탈퇴하기' }));
    await waitFor(() => {
      expect(screen.getByText('회원 탈퇴가 완료되었습니다.')).toBeTruthy();
    });
  });
});
