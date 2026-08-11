// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import MobileStartupScreen, {
  hasCompletedMobileStartup,
  MOBILE_STARTUP_STORAGE_KEY,
  rememberMobileStartup,
} from './MobileStartupScreen';

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe('MOB-18 모바일 시작 화면', () => {
  it('서비스 설명과 3단계 이용 가이드를 표시한다', () => {
    render(<MobileStartupScreen onStart={vi.fn()} onKakaoLogin={vi.fn()} />);

    expect(screen.getByRole('heading', { name: /나에게 맞는 길을/ })).toBeTruthy();
    expect(screen.getByRole('list', { name: '동넷 이용 방법' }).children).toHaveLength(3);
    expect(screen.getByText('로그인 없이 바로 이용할 수 있어요.', { exact: false })).toBeTruthy();
    expect(screen.getByText('선택 기능이에요.', { exact: false })).toBeTruthy();
  });

  it('로그인 없이 시작하기와 카카오 로그인을 별도 행동으로 전달한다', () => {
    const onStart = vi.fn();
    const onKakaoLogin = vi.fn();
    render(<MobileStartupScreen onStart={onStart} onKakaoLogin={onKakaoLogin} />);

    fireEvent.click(screen.getByRole('button', { name: '로그인 없이 시작하기' }));
    fireEvent.click(screen.getByRole('button', { name: '카카오 로그인' }));

    expect(onStart).toHaveBeenCalledOnce();
    expect(onKakaoLogin).toHaveBeenCalledOnce();
    expect(screen.getByRole('button', { name: '카카오 로그인' }).className)
      .toContain('btn--kakao');
  });

  it('완료 상태는 개인정보 없이 버전 키 하나로 저장한다', () => {
    expect(hasCompletedMobileStartup()).toBe(false);
    rememberMobileStartup();
    expect(window.localStorage.getItem(MOBILE_STARTUP_STORAGE_KEY)).toBe('1');
    expect(hasCompletedMobileStartup()).toBe(true);
  });

  it('저장소 쓰기가 차단돼도 시작 처리는 예외를 던지지 않는다', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('blocked');
    });
    expect(() => rememberMobileStartup()).not.toThrow();
  });
});
