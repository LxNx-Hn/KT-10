/**
 * 음성안내(TTS). 브라우저 Web Speech API를 사용한다.
 * 모바일 자동재생 정책과 Chromium의 cancel 직후 speak 무음 회귀를 함께 방어한다.
 */
let koVoice: SpeechSynthesisVoice | null = null;
let activeUtterance: SpeechSynthesisUtterance | null = null;
let pendingSpeak: ReturnType<typeof setTimeout> | null = null;
let primed = false;

function pickKoreanVoice(): SpeechSynthesisVoice | null {
  if (!isSpeechSupported()) return null;
  const voices = window.speechSynthesis.getVoices();
  return (
    voices.find((voice) => voice.lang === 'ko-KR')
    ?? voices.find((voice) => voice.lang.startsWith('ko'))
    ?? null
  );
}

export function isSpeechSupported(): boolean {
  return (
    typeof window !== 'undefined'
    && 'speechSynthesis' in window
    && typeof SpeechSynthesisUtterance !== 'undefined'
  );
}

function clearPending(): void {
  if (pendingSpeak !== null) {
    clearTimeout(pendingSpeak);
    pendingSpeak = null;
  }
}

/**
 * 사용자의 클릭 동작 안에서 무음 발화를 한 번 큐에 넣어 모바일 브라우저의
 * 음성 출력 권한을 활성화한다. 실제 안내를 재생 중이면 건드리지 않는다.
 */
export function primeSpeechOutput(): boolean {
  if (!isSpeechSupported() || primed || activeUtterance) return isSpeechSupported();
  try {
    const utterance = new SpeechSynthesisUtterance('\u00a0');
    utterance.lang = 'ko-KR';
    utterance.volume = 0;
    utterance.onend = () => {
      if (activeUtterance === utterance) activeUtterance = null;
    };
    utterance.onerror = () => {
      if (activeUtterance === utterance) activeUtterance = null;
    };
    activeUtterance = utterance;
    window.speechSynthesis.speak(utterance);
    primed = true;
    return true;
  } catch {
    activeUtterance = null;
    return false;
  }
}

/**
 * 텍스트를 음성으로 읽는다. 진행 중 음성은 중단 후 새로 읽는다.
 * utterance를 모듈에 보관해 일부 모바일 브라우저의 조기 GC를 방지하고,
 * cancel과 speak를 같은 tick에 실행하지 않는다.
 */
export function speak(
  text: string,
  opts: {
    rate?: number;
    onStart?: () => void;
    onEnd?: () => void;
    onError?: () => void;
  } = {},
): boolean {
  const normalized = text.trim();
  if (!isSpeechSupported() || !normalized) return false;
  clearPending();
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(normalized);
  utterance.lang = 'ko-KR';
  utterance.rate = opts.rate ?? 1;
  koVoice = pickKoreanVoice();
  if (koVoice) utterance.voice = koVoice;
  utterance.onstart = () => opts.onStart?.();
  let settled = false;
  const finish = (failed: boolean) => {
    if (settled || activeUtterance !== utterance) return;
    settled = true;
    activeUtterance = null;
    if (failed) opts.onError?.();
    opts.onEnd?.();
  };
  utterance.onend = () => {
    finish(false);
  };
  utterance.onerror = () => {
    finish(true);
  };
  activeUtterance = utterance;
  pendingSpeak = setTimeout(() => {
    pendingSpeak = null;
    if (activeUtterance !== utterance) return;
    try {
      if (window.speechSynthesis.paused) window.speechSynthesis.resume();
      window.speechSynthesis.speak(utterance);
    } catch {
      finish(true);
    }
  }, 0);
  return true;
}

export function stopSpeaking(): void {
  clearPending();
  activeUtterance = null;
  if (isSpeechSupported()) window.speechSynthesis.cancel();
}

if (isSpeechSupported()) {
  const updateVoices = () => {
    koVoice = pickKoreanVoice();
  };
  window.speechSynthesis.addEventListener?.('voiceschanged', updateVoices);
  updateVoices();
}
