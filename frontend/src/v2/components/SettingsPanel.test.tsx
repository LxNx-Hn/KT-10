// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import SettingsPanel from './SettingsPanel';

vi.mock('@/components/KakaoLoginButton', () => ({
  default: () => <button type="button">카카오 로그인</button>,
}));

vi.mock('@/components/AccountWithdrawal', () => ({
  default: () => <button type="button">회원 탈퇴</button>,
}));

vi.mock('@/admin/AdminReviewLink', () => ({
  default: () => null,
}));

afterEach(() => {
  cleanup();
});

describe('SettingsPanel 법적 고지', () => {
  it('로그인 여부와 무관하게 이용약관·개인정보처리방침 링크를 표시한다', () => {
    render(<SettingsPanel largeUi={false} onToggleLargeUi={vi.fn()} />);

    expect(screen.getByRole('heading', { name: '법적 고지' })).toBeTruthy();
    expect(screen.getByRole('link', { name: '이용약관' }).getAttribute('href')).toBe(
      '/terms',
    );
    expect(
      screen.getByRole('link', { name: '개인정보처리방침' }).getAttribute('href'),
    ).toBe('/privacy');
    expect(screen.getByRole('button', { name: '회원 탈퇴' })).toBeTruthy();
  });

  it('큰 글씨 토글과 탈퇴 진입점을 유지한다', () => {
    const onToggleLargeUi = vi.fn();
    render(<SettingsPanel largeUi={false} onToggleLargeUi={onToggleLargeUi} />);

    fireEvent.click(screen.getByRole('button', { name: '큰 글씨와 큰 버튼 사용' }));
    expect(onToggleLargeUi).toHaveBeenCalledOnce();
  });
});
