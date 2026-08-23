import { describe, expect, it } from 'vitest';
import {
  isAndroidPlatform,
  isIosLikePlatform,
  isPwaStandalone,
} from './installPlatform';

describe('isIosLikePlatform', () => {
  it('iPhone Safari UA를 iOS로 본다', () => {
    expect(isIosLikePlatform(
      'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)',
      'iPhone',
      5,
    )).toBe(true);
  });

  it('classic iPad UA를 iOS로 본다', () => {
    expect(isIosLikePlatform(
      'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)',
      'iPad',
      5,
    )).toBe(true);
  });

  it('iPadOS desktop-like MacIntel + multi-touch를 iOS로 본다', () => {
    expect(isIosLikePlatform(
      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
      'MacIntel',
      5,
    )).toBe(true);
  });

  it('real Mac desktop은 iOS로 보지 않는다', () => {
    expect(isIosLikePlatform(
      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
      'MacIntel',
      0,
    )).toBe(false);
    expect(isIosLikePlatform(
      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
      'MacIntel',
      1,
    )).toBe(false);
  });

  it('Android는 iOS로 보지 않는다', () => {
    expect(isIosLikePlatform(
      'Mozilla/5.0 (Linux; Android 14; Pixel 8)',
      'Linux armv81',
      5,
    )).toBe(false);
  });

  it('Windows desktop은 iOS로 보지 않는다', () => {
    expect(isIosLikePlatform(
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
      'Win32',
      0,
    )).toBe(false);
  });
});

describe('isAndroidPlatform', () => {
  it('Android UA를 감지한다', () => {
    expect(isAndroidPlatform('Mozilla/5.0 (Linux; Android 14)')).toBe(true);
  });
});

describe('isPwaStandalone', () => {
  it('navigator.standalone이 true면 standalone이다', () => {
    expect(isPwaStandalone({ standalone: true })).toBe(true);
  });

  it('display-mode standalone이면 standalone이다', () => {
    expect(isPwaStandalone({ displayModeStandalone: true })).toBe(true);
  });

  it('browser mode면 standalone이 아니다', () => {
    expect(isPwaStandalone({ standalone: false, displayModeStandalone: false })).toBe(false);
  });
});
