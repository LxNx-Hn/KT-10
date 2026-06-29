/**
 * 음성명령 입력(STT) + 명령 실행 + 음성안내(TTS) 통합 훅.
 * Web Speech API(SpeechRecognition)를 사용하며 미지원 시 supported=false.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useAppStore } from '@/store/appStore';
import { adapters } from '@/adapters';
import { parseCommand, type VoiceAction } from './commandParser';
import { speak } from './synthesis';

type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((e: any) => void) | null;
  onerror: ((e: any) => void) | null;
  onend: (() => void) | null;
};

function getRecognitionCtor(): (new () => SpeechRecognitionLike) | null {
  if (typeof window === 'undefined') return null;
  const w = window as any;
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

export function isVoiceInputSupported(): boolean {
  return getRecognitionCtor() !== null;
}

/** 말하고, 마지막 안내 문장을 저장(반복 명령 대비) */
function speakAndRemember(text: string) {
  if (!text) return;
  useAppStore.getState().setLastSpoken(text);
  speak(text);
}

/** 파싱된 명령들을 순차 실행하고 음성 피드백을 제공한다. */
async function executeActions(actions: VoiceAction[]): Promise<void> {
  const store = useAppStore.getState();
  let shouldResearch = false;
  let profileChanged = false;

  for (const a of actions) {
    switch (a.kind) {
      case 'set-profile':
        store.setProfile(a.profile);
        profileChanged = true;
        break;

      case 'low-floor-priority':
        if (!useAppStore.getState().options.lowFloorPriority)
          store.toggleLowFloorPriority();
        speakAndRemember('저상버스 우선으로 다시 평가했어요.');
        break;

      case 'weather-avoid':
        if (!useAppStore.getState().options.weatherAvoid) store.toggleWeatherAvoid();
        speakAndRemember('날씨 위험을 피하는 기준으로 다시 평가했어요.');
        break;

      case 'search-destination': {
        const results = await adapters.places.searchPlaces(a.query);
        if (results.length === 0) {
          speakAndRemember(`${a.query} 장소를 찾지 못했어요. 다시 말씀해 주세요.`);
          break;
        }
        store.setDestination(results[0]);
        if (!useAppStore.getState().origin) store.loadDemoOd();
        shouldResearch = true;
        break;
      }

      case 'research':
        shouldResearch = true;
        break;

      case 'describe-route': {
        const rec = useAppStore.getState().recommendations[a.index];
        if (!rec) {
          speakAndRemember(`${a.index + 1}번 경로가 없어요.`);
          break;
        }
        store.selectRoute(rec.route.id);
        const text = `${rec.score.voiceSummary} 추천 이유, ${rec.score.reasons.join(' ')}`;
        speakAndRemember(text);
        break;
      }

      case 'select-route': {
        const rec = useAppStore.getState().recommendations[a.index];
        if (!rec) {
          speakAndRemember(`${a.index + 1}번 경로가 없어요.`);
          break;
        }
        store.selectRoute(rec.route.id);
        speakAndRemember(`${a.index + 1}번 경로로 안내를 시작할게요. ${rec.score.voiceSummary}`);
        break;
      }

      case 'repeat':
        speak(useAppStore.getState().lastSpoken || '다시 안내할 내용이 없어요.');
        break;

      case 'unknown':
        speakAndRemember('명령을 이해하지 못했어요. 다시 말씀해 주세요.');
        break;
    }
  }

  if (shouldResearch) {
    await store.search();
    const top = useAppStore.getState().recommendations[0];
    if (top) speakAndRemember(`경로를 찾았어요. ${top.score.voiceSummary}`);
  } else if (profileChanged) {
    const top = useAppStore.getState().recommendations[0];
    if (top) speakAndRemember(`기준을 바꿨어요. 추천 1순위는 ${top.score.voiceSummary}`);
  }
}

export interface VoiceControl {
  supported: boolean;
  listening: boolean;
  transcript: string;
  start: () => void;
  stop: () => void;
}

export function useVoiceControl(): VoiceControl {
  const [listening, setListening] = useState(false);
  const [transcript, setTranscript] = useState('');
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const supported = isVoiceInputSupported();

  useEffect(() => {
    const Ctor = getRecognitionCtor();
    if (!Ctor) return;
    const rec = new Ctor();
    rec.lang = 'ko-KR';
    rec.continuous = false;
    rec.interimResults = false;

    rec.onresult = (e: any) => {
      const text: string = e.results?.[0]?.[0]?.transcript ?? '';
      setTranscript(text);
      void executeActions(parseCommand(text));
    };
    rec.onerror = () => setListening(false);
    rec.onend = () => setListening(false);

    recRef.current = rec;
    return () => rec.abort();
  }, []);

  const start = useCallback(() => {
    if (!recRef.current || listening) return;
    try {
      setTranscript('');
      recRef.current.start();
      setListening(true);
    } catch {
      setListening(false);
    }
  }, [listening]);

  const stop = useCallback(() => {
    recRef.current?.stop();
    setListening(false);
  }, []);

  return { supported, listening, transcript, start, stop };
}
