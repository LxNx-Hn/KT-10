// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import InstallPrompt from './InstallPrompt';

type EnvOptions = {
  userAgent?: string;
  platform?: string;
  maxTouchPoints?: number;
  standalone?: boolean;
  displayModeStandalone?: boolean;
};

function mockInstallEnvironment(options: EnvOptions = {}) {
  const userAgent = options.userAgent
    ?? 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36';
  const platform = options.platform ?? 'Linux armv81';
  const maxTouchPoints = options.maxTouchPoints ?? 5;

  Object.defineProperty(window.navigator, 'userAgent', {
    configurable: true,
    value: userAgent,
  });
  Object.defineProperty(window.navigator, 'platform', {
    configurable: true,
    value: platform,
  });
  Object.defineProperty(window.navigator, 'maxTouchPoints', {
    configurable: true,
    value: maxTouchPoints,
  });
  Object.defineProperty(window.navigator, 'standalone', {
    configurable: true,
    value: options.standalone ?? false,
  });

  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query === '(display-mode: standalone)'
      && options.displayModeStandalone === true,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

function dispatchBeforeInstallPrompt() {
  const event = new Event('beforeinstallprompt', {
    cancelable: true,
  }) as Event & {
    prompt: ReturnType<typeof vi.fn>;
    userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>;
  };
  event.prompt = vi.fn().mockResolvedValue(undefined);
  event.userChoice = Promise.resolve({
    outcome: 'dismissed',
    platform: '',
  });
  act(() => {
    window.dispatchEvent(event);
  });
  return event;
}

beforeEach(() => {
  mockInstallEnvironment();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('InstallPrompt Android', () => {
  it('beforeinstallprompt 전에는 Android 배너를 표시하지 않는다', () => {
    render(<InstallPrompt />);
    expect(screen.queryByRole('complementary', { name: '앱 설치 안내' })).toBeNull();
  });

  it('beforeinstallprompt 발생 시 Android 설치 배너를 표시한다', () => {
    render(<InstallPrompt />);
    dispatchBeforeInstallPrompt();
    expect(screen.getByText('홈 화면에서 바로 길찾기')).toBeTruthy();
    expect(screen.getByRole('button', { name: '설치' })).toBeTruthy();
  });

  it('설치 클릭 시 prompt()를 정확히 한 번 호출한다', async () => {
    render(<InstallPrompt />);
    const event = dispatchBeforeInstallPrompt();
    fireEvent.click(screen.getByRole('button', { name: '설치' }));
    await act(async () => {
      await event.userChoice;
    });
    expect(event.prompt).toHaveBeenCalledTimes(1);
  });

  it('userChoice 이후 deferred event를 제거한다', async () => {
    render(<InstallPrompt />);
    dispatchBeforeInstallPrompt();
    fireEvent.click(screen.getByRole('button', { name: '설치' }));
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.queryByRole('complementary', { name: '앱 설치 안내' })).toBeNull();
  });

  it('appinstalled 발생 시 설치 배너를 제거한다', () => {
    render(<InstallPrompt />);
    dispatchBeforeInstallPrompt();
    act(() => {
      window.dispatchEvent(new Event('appinstalled'));
    });
    expect(screen.queryByRole('complementary', { name: '앱 설치 안내' })).toBeNull();
  });

  it('닫기 클릭 시 Android 안내를 제거한다', () => {
    render(<InstallPrompt />);
    dispatchBeforeInstallPrompt();
    fireEvent.click(screen.getByRole('button', { name: '설치 안내 닫기' }));
    expect(screen.queryByRole('complementary', { name: '앱 설치 안내' })).toBeNull();
  });
});

describe('InstallPrompt iOS / iPadOS', () => {
  it('iPhone Safari-like 환경에서 iOS 설치 안내를 표시한다', () => {
    mockInstallEnvironment({
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)',
      platform: 'iPhone',
      maxTouchPoints: 5,
    });
    render(<InstallPrompt />);
    expect(screen.getByText('동넷을 홈 화면에 추가하세요')).toBeTruthy();
    expect(screen.getByRole('button', { name: '설치 방법 보기' })).toBeTruthy();
  });

  it('navigator.standalone이 true면 iOS 안내를 표시하지 않는다', () => {
    mockInstallEnvironment({
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)',
      platform: 'iPhone',
      maxTouchPoints: 5,
      standalone: true,
    });
    render(<InstallPrompt />);
    expect(screen.queryByRole('complementary', { name: '앱 설치 안내' })).toBeNull();
  });

  it('display-mode standalone이면 iOS 안내를 표시하지 않는다', () => {
    mockInstallEnvironment({
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)',
      platform: 'iPhone',
      maxTouchPoints: 5,
      displayModeStandalone: true,
    });
    render(<InstallPrompt />);
    expect(screen.queryByRole('complementary', { name: '앱 설치 안내' })).toBeNull();
  });

  it('classic iPad UA에서 iOS 안내를 표시한다', () => {
    mockInstallEnvironment({
      userAgent: 'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)',
      platform: 'iPad',
      maxTouchPoints: 5,
    });
    render(<InstallPrompt />);
    expect(screen.getByText('동넷을 홈 화면에 추가하세요')).toBeTruthy();
  });

  it('iPadOS desktop-like MacIntel + multi-touch에서 iOS 안내를 표시한다', () => {
    mockInstallEnvironment({
      userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
      platform: 'MacIntel',
      maxTouchPoints: 5,
    });
    render(<InstallPrompt />);
    expect(screen.getByText('동넷을 홈 화면에 추가하세요')).toBeTruthy();
  });

  it('real Mac desktop-like 환경에서는 iOS 안내를 표시하지 않는다', () => {
    mockInstallEnvironment({
      userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
      platform: 'MacIntel',
      maxTouchPoints: 0,
    });
    render(<InstallPrompt />);
    expect(screen.queryByRole('complementary', { name: '앱 설치 안내' })).toBeNull();
  });

  it('Android에서는 iOS 안내를 표시하지 않는다', () => {
    mockInstallEnvironment({
      userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8)',
      platform: 'Linux armv81',
      maxTouchPoints: 5,
    });
    render(<InstallPrompt />);
    expect(screen.queryByText('동넷을 홈 화면에 추가하세요')).toBeNull();
  });

  it('Windows desktop에서는 iOS 안내를 표시하지 않는다', () => {
    mockInstallEnvironment({
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
      platform: 'Win32',
      maxTouchPoints: 0,
    });
    render(<InstallPrompt />);
    expect(screen.queryByRole('complementary', { name: '앱 설치 안내' })).toBeNull();
  });

  it('설치 방법 보기 클릭 시 3단계 안내를 표시한다', () => {
    mockInstallEnvironment({
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)',
      platform: 'iPhone',
      maxTouchPoints: 5,
    });
    render(<InstallPrompt />);
    fireEvent.click(screen.getByRole('button', { name: '설치 방법 보기' }));
    expect(screen.getByText('동넷 설치하기')).toBeTruthy();
    expect(screen.getByText('브라우저의 공유 버튼을 눌러주세요.')).toBeTruthy();
    expect(screen.getByText('"홈 화면에 추가"를 선택하세요.')).toBeTruthy();
    expect(screen.getByText('오른쪽 위 "추가"를 눌러주세요.')).toBeTruthy();
  });

  it('iOS 안내 닫기 클릭 시 안내를 제거한다', () => {
    mockInstallEnvironment({
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)',
      platform: 'iPhone',
      maxTouchPoints: 5,
    });
    render(<InstallPrompt />);
    fireEvent.click(screen.getByRole('button', { name: '설치 안내 닫기' }));
    expect(screen.queryByRole('complementary', { name: '앱 설치 안내' })).toBeNull();
  });
});

describe('InstallPrompt platform precedence', () => {
  const iphoneEnv = {
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)',
    platform: 'iPhone',
    maxTouchPoints: 5,
  } as const;

  it('iOS-like + deferredPrompt 동시 조건에서 iOS guide만 표시한다', () => {
    mockInstallEnvironment(iphoneEnv);
    render(<InstallPrompt />);
    dispatchBeforeInstallPrompt();
    expect(screen.getByText('동넷을 홈 화면에 추가하세요')).toBeTruthy();
    expect(screen.getByRole('button', { name: '설치 방법 보기' })).toBeTruthy();
    expect(screen.queryByText('홈 화면에서 바로 길찾기')).toBeNull();
    expect(screen.queryByRole('button', { name: '설치' })).toBeNull();
  });

  it('iOS-like 상태에서 beforeinstallprompt를 Android deferredPrompt로 저장하지 않는다', () => {
    mockInstallEnvironment(iphoneEnv);
    render(<InstallPrompt />);
    const event = dispatchBeforeInstallPrompt();
    expect(event.defaultPrevented).toBe(true);
    expect(screen.queryByRole('button', { name: '설치' })).toBeNull();
    expect(screen.getByText('동넷을 홈 화면에 추가하세요')).toBeTruthy();
  });

  it('Android deferredPrompt 저장 후 iOS-like로 전환하면 Android UI가 사라지고 iOS guide만 표시한다', () => {
    mockInstallEnvironment();
    const { rerender } = render(<InstallPrompt />);
    dispatchBeforeInstallPrompt();
    expect(screen.getByText('홈 화면에서 바로 길찾기')).toBeTruthy();

    mockInstallEnvironment(iphoneEnv);
    rerender(<InstallPrompt />);
    expect(screen.queryByText('홈 화면에서 바로 길찾기')).toBeNull();
    expect(screen.queryByRole('button', { name: '설치' })).toBeNull();
    expect(screen.getByText('동넷을 홈 화면에 추가하세요')).toBeTruthy();
  });

  it('iOS guide 닫기 후 Android 배너로 fallback하지 않는다', () => {
    mockInstallEnvironment();
    const { rerender } = render(<InstallPrompt />);
    dispatchBeforeInstallPrompt();

    mockInstallEnvironment(iphoneEnv);
    rerender(<InstallPrompt />);
    fireEvent.click(screen.getByRole('button', { name: '설치 안내 닫기' }));

    expect(screen.queryByRole('complementary', { name: '앱 설치 안내' })).toBeNull();
    expect(screen.queryByText('홈 화면에서 바로 길찾기')).toBeNull();
    expect(screen.queryByText('동넷을 홈 화면에 추가하세요')).toBeNull();
    expect(screen.queryByRole('button', { name: '설치' })).toBeNull();
  });

  it('non-iOS Android/Chromium beforeinstallprompt flow를 유지한다', async () => {
    render(<InstallPrompt />);
    const event = dispatchBeforeInstallPrompt();
    expect(screen.getByText('홈 화면에서 바로 길찾기')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '설치' }));
    await act(async () => {
      await event.userChoice;
    });
    expect(event.prompt).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('complementary', { name: '앱 설치 안내' })).toBeNull();
  });

  it('standalone이면 Android/iOS install UI를 모두 표시하지 않는다', () => {
    mockInstallEnvironment({
      ...iphoneEnv,
      standalone: true,
    });
    render(<InstallPrompt />);
    dispatchBeforeInstallPrompt();
    expect(screen.queryByRole('complementary', { name: '앱 설치 안내' })).toBeNull();
    expect(screen.queryByText('동넷을 홈 화면에 추가하세요')).toBeNull();
    expect(screen.queryByText('홈 화면에서 바로 길찾기')).toBeNull();

    mockInstallEnvironment({ displayModeStandalone: true });
    render(<InstallPrompt />);
    dispatchBeforeInstallPrompt();
    expect(screen.queryByRole('complementary', { name: '앱 설치 안내' })).toBeNull();
  });
});

describe('InstallPrompt lifecycle', () => {
  it('iOS-like + beforeinstallprompt에서 Android UI 대신 iOS guide만 표시한다', () => {
    mockInstallEnvironment({
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)',
      platform: 'iPhone',
      maxTouchPoints: 5,
    });
    render(<InstallPrompt />);
    dispatchBeforeInstallPrompt();
    expect(screen.getByText('동넷을 홈 화면에 추가하세요')).toBeTruthy();
    expect(screen.queryByText('홈 화면에서 바로 길찾기')).toBeNull();
    expect(screen.queryByRole('button', { name: '설치' })).toBeNull();
  });

  it('unmount 시 event listener를 정리한다', () => {
    const removeSpy = vi.spyOn(window, 'removeEventListener');
    const { unmount } = render(<InstallPrompt />);
    unmount();
    expect(removeSpy).toHaveBeenCalledWith(
      'beforeinstallprompt',
      expect.any(Function),
    );
    expect(removeSpy).toHaveBeenCalledWith(
      'appinstalled',
      expect.any(Function),
    );
  });

  it('rerender 후 duplicate listener 없이 Android prompt를 한 번만 처리한다', async () => {
    const addSpy = vi.spyOn(window, 'addEventListener');
    const { rerender } = render(<InstallPrompt />);
    expect(
      addSpy.mock.calls.filter(([type]) => type === 'beforeinstallprompt').length,
    ).toBe(1);

    const event = dispatchBeforeInstallPrompt();
    rerender(<InstallPrompt />);
    fireEvent.click(screen.getByRole('button', { name: '설치' }));
    await act(async () => {
      await event.userChoice;
    });
    expect(event.prompt).toHaveBeenCalledTimes(1);
  });
});
