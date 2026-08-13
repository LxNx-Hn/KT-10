// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const authMocks = vi.hoisted(() => ({
  startKakaoLogin: vi.fn(),
  resolveSignupStatus: vi.fn().mockResolvedValue({ status: 'pending' }),
  completeSignup: vi.fn(),
  cancelSignup: vi.fn(),
}));

vi.mock('@/auth/api', () => authMocks);
vi.mock('@/v2/MapFirstApp', () => ({
  default: () => <main id="main-content">지도 홈</main>,
}));
vi.mock('@/components/VoiceChatDock', () => ({
  default: () => null,
}));

import App from './App';
import { MOBILE_STARTUP_STORAGE_KEY } from './components/MobileStartupScreen';

function stubMobileViewport(matches: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: query === '(max-width: 479px)' ? matches : false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(() => true),
    } as MediaQueryList)),
  );
}

beforeEach(() => {
  window.localStorage.clear();
  window.history.pushState({}, '', '/');
  authMocks.startKakaoLogin.mockClear();
});

afterEach(() => {
  cleanup();
  window.history.pushState({}, '', '/');
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('MOB-18 앱 진입 계약', () => {
  it('첫 방문에서는 시작 화면을 먼저 보여주고 완료 상태를 저장한다', () => {
    stubMobileViewport(true);
    render(<App />);

    expect(screen.queryByText('지도 홈')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '로그인 없이 시작하기' }));

    expect(screen.getByText('지도 홈')).toBeTruthy();
    expect(window.localStorage.getItem(MOBILE_STARTUP_STORAGE_KEY)).toBe('1');
  });

  it('모바일 재방문자는 시작 화면을 건너뛰고 지도 홈으로 진입한다', () => {
    stubMobileViewport(true);
    window.localStorage.setItem(MOBILE_STARTUP_STORAGE_KEY, '1');
    render(<App />);

    expect(screen.getByText('지도 홈')).toBeTruthy();
    expect(screen.queryByRole('button', { name: '로그인 없이 시작하기' })).toBeNull();
  });

  it('데스크톱 첫 방문에서도 시작 화면을 먼저 보여준다', () => {
    stubMobileViewport(false);
    render(<App />);

    expect(screen.queryByText('지도 홈')).toBeNull();
    expect(screen.getByRole('button', { name: '로그인 없이 시작하기' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: '로그인 없이 시작하기' }));
    expect(screen.getByText('지도 홈')).toBeTruthy();
  });

  it('카카오 로그인 선택도 시작 완료를 저장한 뒤 기존 OAuth 진입을 호출한다', () => {
    stubMobileViewport(true);
    render(<App />);

    fireEvent.click(screen.getByRole('button', { name: '카카오 로그인' }));

    expect(window.localStorage.getItem(MOBILE_STARTUP_STORAGE_KEY)).toBe('1');
    expect(authMocks.startKakaoLogin).toHaveBeenCalledOnce();
  });

  it('startup 미완료 상태에서도 /terms·/privacy는 시작 화면보다 우선한다', () => {
    stubMobileViewport(true);
    window.history.pushState({}, '', '/terms');
    const { unmount } = render(<App />);
    expect(screen.getByRole('heading', { level: 1, name: '이용약관' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: '로그인 없이 시작하기' })).toBeNull();
    unmount();

    window.history.pushState({}, '', '/privacy');
    render(<App />);
    expect(screen.getByRole('heading', { level: 1, name: '개인정보처리방침' })).toBeTruthy();
    expect(screen.queryByText('지도 홈')).toBeNull();
  });

  it('startup 미완료 상태에서도 /signup/consent는 시작 화면보다 우선한다', async () => {
    stubMobileViewport(true);
    window.history.pushState({}, '', '/signup/consent');
    render(<App />);
    expect(
      await screen.findByRole('heading', { level: 1, name: '동넷 시작하기' }),
    ).toBeTruthy();
    expect(screen.queryByRole('button', { name: '로그인 없이 시작하기' })).toBeNull();
    expect(screen.queryByText('지도 홈')).toBeNull();
  });

  it('저장소가 차단돼도 현재 세션에서는 지도 홈으로 진입한다', () => {
    stubMobileViewport(true);
    window.history.pushState({}, '', '/');
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('blocked');
    });
    render(<App />);

    fireEvent.click(screen.getByRole('button', { name: '로그인 없이 시작하기' }));
    expect(screen.getByText('지도 홈')).toBeTruthy();
  });
});
