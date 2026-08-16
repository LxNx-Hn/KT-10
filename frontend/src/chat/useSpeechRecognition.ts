/**
 * 저수준 STT 훅. Web Speech API SpeechRecognition 래핑.
 * interim(중간 인식) 결과를 실시간으로 콜백하고, 최종 문장은 onFinal 로 전달한다.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((e: any) => void) | null;
  onerror: ((e: SpeechRecognitionErrorLike) => void) | null;
  onend: (() => void) | null;
  onstart: (() => void) | null;
};

export type SpeechRecognitionErrorLike = {
  error?: string;
  message?: string;
};

function getRecognitionCtor(): (new () => SpeechRecognitionLike) | null {
  if (typeof window === 'undefined') return null;
  const w = window as any;
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

export function isVoiceInputSupported(): boolean {
  return getRecognitionCtor() !== null;
}

export function speechRecognitionErrorCode(
  event: SpeechRecognitionErrorLike | undefined,
): string {
  return typeof event?.error === 'string' && event.error
    ? event.error
    : 'unknown';
}

export function speechRecognitionUserMessage(code: string): string {
  switch (code) {
    case 'not-allowed':
    case 'service-not-allowed':
      return '마이크 권한을 확인해 주세요.';
    case 'audio-capture':
      return '마이크를 사용할 수 없어요.';
    case 'network':
      return '음성 인식 연결에 문제가 발생했어요.';
    case 'no-speech':
      return '음성이 들리지 않았어요. 다시 말씀해 주세요.';
    default:
      return '음성 인식을 시작하지 못했어요.';
  }
}

export interface SpeechCallbacks {
  onInterim?: (text: string) => void;
  onFinal?: (text: string) => void;
  onStart?: () => void;
  onEnd?: () => void;
  onError?: (code: string) => void;
}

let startFromUserGesture: (() => void) | null = null;

export function registerSpeechRecognitionStart(
  handler: (() => void) | null,
): void {
  startFromUserGesture = handler;
}

/** 원본 클릭 스택에서 SpeechRecognition.start()를 호출한다. */
export function startSpeechRecognitionFromUserGesture(): void {
  startFromUserGesture?.();
}

export function useSpeechRecognition(cb: SpeechCallbacks) {
  const [listening, setListening] = useState(false);
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const listeningRef = useRef(false);
  const cbRef = useRef(cb);
  cbRef.current = cb;
  const supported = isVoiceInputSupported();

  const bindRecognition = useCallback((rec: SpeechRecognitionLike) => {
    rec.lang = 'ko-KR';
    rec.continuous = false;
    rec.interimResults = true;
    rec.onstart = () => {
      listeningRef.current = true;
      setListening(true);
      cbRef.current.onStart?.();
    };
    rec.onresult = (e: any) => {
      let interim = '';
      let final = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) final += r[0].transcript;
        else interim += r[0].transcript;
      }
      if (interim) cbRef.current.onInterim?.(interim);
      if (final) cbRef.current.onFinal?.(final.trim());
    };
    rec.onerror = (event: SpeechRecognitionErrorLike) => {
      listeningRef.current = false;
      setListening(false);
      const code = speechRecognitionErrorCode(event);
      if (code === 'aborted') return;
      cbRef.current.onError?.(code);
    };
    rec.onend = () => {
      listeningRef.current = false;
      setListening(false);
      cbRef.current.onEnd?.();
    };
  }, []);

  const ensureRecognition = useCallback((): SpeechRecognitionLike | null => {
    if (recRef.current) return recRef.current;
    const Ctor = getRecognitionCtor();
    if (!Ctor) return null;
    const rec = new Ctor();
    bindRecognition(rec);
    recRef.current = rec;
    return rec;
  }, [bindRecognition]);

  useEffect(() => {
    ensureRecognition();
    return () => recRef.current?.abort();
  }, [ensureRecognition]);

  const start = useCallback(() => {
    if (listeningRef.current) return;
    const rec = ensureRecognition();
    if (!rec) return;
    try {
      rec.start();
    } catch {
      /* 이미 시작된 경우 무시 */
    }
  }, [ensureRecognition]);

  const stop = useCallback(() => {
    recRef.current?.stop();
  }, []);

  return { supported, listening, start, stop };
}
