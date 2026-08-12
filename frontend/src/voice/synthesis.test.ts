// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

class FakeUtterance {
  text: string;
  lang = '';
  rate = 1;
  pitch = 1;
  volume = 1;
  voice: SpeechSynthesisVoice | null = null;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(text: string) {
    this.text = text;
  }
}

const synthesis = {
  paused: false,
  cancel: vi.fn(),
  speak: vi.fn(),
  resume: vi.fn(),
  getVoices: vi.fn(() => [{ lang: 'ko-KR', name: 'Korean' }]),
  addEventListener: vi.fn(),
};

beforeEach(() => {
  vi.useFakeTimers();
  vi.resetModules();
  Object.defineProperty(window, 'speechSynthesis', {
    configurable: true,
    value: synthesis,
  });
  vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance);
  Object.values(synthesis).forEach((value) => {
    if (typeof value === 'function' && 'mockClear' in value) value.mockClear();
  });
  synthesis.paused = false;
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('브라우저 음성 출력', () => {
  it('cancel 다음 tick에 한국어 utterance를 재생하고 종료 콜백을 전달한다', async () => {
    const { speak } = await import('./synthesis');
    const onEnd = vi.fn();

    expect(speak('안녕하세요', { onEnd })).toBe(true);
    expect(synthesis.cancel).toHaveBeenCalledTimes(1);
    expect(synthesis.speak).not.toHaveBeenCalled();

    vi.runAllTimers();
    expect(synthesis.speak).toHaveBeenCalledTimes(1);
    const utterance = synthesis.speak.mock.calls[0][0] as unknown as FakeUtterance;
    expect(utterance.text).toBe('안녕하세요');
    expect(utterance.lang).toBe('ko-KR');
    expect(utterance.rate).toBe(0.95);
    expect((utterance.voice as unknown as { lang: string }).lang).toBe('ko-KR');
    utterance.onend?.();
    expect(onEnd).toHaveBeenCalledTimes(1);
  });

  it('선호 한국어 음성과 수치 단위를 자연스러운 발화로 사용한다', async () => {
    synthesis.getVoices.mockReturnValue([
      { lang: 'ko-KR', name: 'Korean Basic', localService: false },
      { lang: 'ko-KR', name: 'Microsoft SunHi Online', localService: true },
    ] as unknown as SpeechSynthesisVoice[]);
    const { speak } = await import('./synthesis');

    speak('도보 14000m, 평균 경사 5.2%');
    vi.runAllTimers();

    const utterance = synthesis.speak.mock.calls[0][0] as unknown as FakeUtterance;
    expect(utterance.text).toBe('도보 14000미터, 평균 경사 5.2퍼센트');
    expect((utterance.voice as unknown as { name: string }).name).toBe('Microsoft SunHi Online');
  });

  it('사용자 클릭에서 무음 priming을 한 번만 수행한다', async () => {
    const { primeSpeechOutput } = await import('./synthesis');

    expect(primeSpeechOutput()).toBe(true);
    expect(primeSpeechOutput()).toBe(true);
    expect(synthesis.speak).toHaveBeenCalledTimes(1);
    const utterance = synthesis.speak.mock.calls[0][0] as unknown as FakeUtterance;
    expect(utterance.volume).toBe(0);
  });

  it('정지하면 아직 예약된 발화를 재생하지 않는다', async () => {
    const { speak, stopSpeaking } = await import('./synthesis');

    speak('취소할 안내');
    stopSpeaking();
    vi.runAllTimers();

    expect(synthesis.speak).not.toHaveBeenCalled();
    expect(synthesis.cancel).toHaveBeenCalledTimes(2);
  });

  it('취소된 이전 발화의 지연 종료 이벤트가 새 발화를 끝내지 않는다', async () => {
    const { speak } = await import('./synthesis');
    const oldEnd = vi.fn();
    const newEnd = vi.fn();

    speak('이전 안내', { onEnd: oldEnd });
    vi.runAllTimers();
    const oldUtterance = synthesis.speak.mock.calls[0][0] as unknown as FakeUtterance;

    speak('새 안내', { onEnd: newEnd });
    vi.runAllTimers();
    const newUtterance = synthesis.speak.mock.calls[1][0] as unknown as FakeUtterance;
    oldUtterance.onerror?.();

    expect(oldEnd).not.toHaveBeenCalled();
    expect(newEnd).not.toHaveBeenCalled();
    newUtterance.onend?.();
    expect(newEnd).toHaveBeenCalledTimes(1);
  });
});
