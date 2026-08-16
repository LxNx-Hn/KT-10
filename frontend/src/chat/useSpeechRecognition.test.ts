// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import {
  isVoiceInputSupported,
  registerSpeechRecognitionStart,
  speechRecognitionUserMessage,
  startSpeechRecognitionFromUserGesture,
  useSpeechRecognition,
} from './useSpeechRecognition';

type RecHandlers = {
  start: ReturnType<typeof vi.fn>;
  stop: ReturnType<typeof vi.fn>;
  abort: ReturnType<typeof vi.fn>;
  onstart: (() => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  onend: (() => void) | null;
  onresult: ((e: unknown) => void) | null;
};

function installRecognition() {
  const instances: RecHandlers[] = [];

  function Recognition() {
    const rec = {
      lang: '',
      continuous: false,
      interimResults: false,
      start: vi.fn(function start(this: typeof rec) {
        this.onstart?.();
      }),
      stop: vi.fn(),
      abort: vi.fn(),
      onstart: null as RecHandlers['onstart'],
      onerror: null as RecHandlers['onerror'],
      onend: null as RecHandlers['onend'],
      onresult: null as RecHandlers['onresult'],
    };
    instances.push(rec);
    return rec;
  }

  vi.stubGlobal('SpeechRecognition', Recognition);
  return instances;
}

afterEach(() => {
  registerSpeechRecognitionStart(null);
  vi.unstubAllGlobals();
});

describe('speechRecognitionUserMessage', () => {
  it('browser error code를 사용자 문구로 구분한다', () => {
    expect(speechRecognitionUserMessage('not-allowed')).toBe(
      '마이크 권한을 확인해 주세요.',
    );
    expect(speechRecognitionUserMessage('service-not-allowed')).toBe(
      '마이크 권한을 확인해 주세요.',
    );
    expect(speechRecognitionUserMessage('audio-capture')).toBe(
      '마이크를 사용할 수 없어요.',
    );
    expect(speechRecognitionUserMessage('network')).toBe(
      '음성 인식 연결에 문제가 발생했어요.',
    );
    expect(speechRecognitionUserMessage('no-speech')).toBe(
      '음성이 들리지 않았어요. 다시 말씀해 주세요.',
    );
    expect(speechRecognitionUserMessage('unknown')).toBe(
      '음성 인식을 시작하지 못했어요.',
    );
  });
});

describe('useSpeechRecognition', () => {
  let instances: ReturnType<typeof installRecognition>;

  beforeEach(() => {
    instances = installRecognition();
  });

  it('SpeechRecognition이 있으면 supported다', () => {
    expect(isVoiceInputSupported()).toBe(true);
  });

  it('start는 한 번만 호출되고 error code를 보존한다', () => {
    const onError = vi.fn();
    const onEnd = vi.fn();
    const { result } = renderHook(() => useSpeechRecognition({ onError, onEnd }));

    act(() => {
      result.current.start();
      result.current.start();
    });
    expect(instances[0]?.start).toHaveBeenCalledTimes(1);

    act(() => {
      instances[0]?.onerror?.({ error: 'not-allowed' });
    });
    expect(onError).toHaveBeenCalledWith('not-allowed');

    act(() => {
      instances[0]?.onend?.();
    });
    expect(onEnd).toHaveBeenCalled();
    expect(result.current.listening).toBe(false);
  });

  it('aborted는 오류 콜백을 호출하지 않는다', () => {
    const onError = vi.fn();
    const { result } = renderHook(() => useSpeechRecognition({ onError }));
    act(() => {
      result.current.start();
      instances[0]?.onerror?.({ error: 'aborted' });
    });
    expect(onError).not.toHaveBeenCalled();
  });

  it('listening 상태가 바뀌어도 start 함수 identity는 유지된다', () => {
    const { result } = renderHook(() => useSpeechRecognition({}));
    const firstStart = result.current.start;
    act(() => {
      result.current.start();
    });
    expect(result.current.listening).toBe(true);
    expect(result.current.start).toBe(firstStart);
    act(() => {
      result.current.start();
    });
    expect(instances[0]?.start).toHaveBeenCalledTimes(1);
  });
});

describe('user gesture start 등록', () => {
  it('등록된 start를 클릭 스택에서 바로 호출한다', () => {
    const start = vi.fn();
    registerSpeechRecognitionStart(start);
    startSpeechRecognitionFromUserGesture();
    expect(start).toHaveBeenCalledTimes(1);
  });

  it('cleanup 이후 request는 dead callback을 호출하지 않는다', () => {
    const start = vi.fn();
    registerSpeechRecognitionStart(start);
    registerSpeechRecognitionStart(null);
    startSpeechRecognitionFromUserGesture();
    expect(start).not.toHaveBeenCalled();
  });
});
