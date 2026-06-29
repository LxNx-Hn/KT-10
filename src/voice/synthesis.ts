/**
 * 음성안내(TTS). Web Speech API SpeechSynthesis 사용.
 * 한국어 음성을 우선 선택하고, 미지원 환경에서는 조용히 무시한다.
 */
let koVoice: SpeechSynthesisVoice | null = null;

function pickKoreanVoice(): SpeechSynthesisVoice | null {
  if (!('speechSynthesis' in window)) return null;
  const voices = window.speechSynthesis.getVoices();
  return (
    voices.find((v) => v.lang === 'ko-KR') ??
    voices.find((v) => v.lang.startsWith('ko')) ??
    null
  );
}

export function isSpeechSupported(): boolean {
  return typeof window !== 'undefined' && 'speechSynthesis' in window;
}

/** 텍스트를 음성으로 읽는다. 진행 중 음성은 중단 후 새로 읽는다. */
export function speak(text: string, opts: { rate?: number } = {}): void {
  if (!isSpeechSupported() || !text) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = 'ko-KR';
  u.rate = opts.rate ?? 1;
  if (!koVoice) koVoice = pickKoreanVoice();
  if (koVoice) u.voice = koVoice;
  window.speechSynthesis.speak(u);
}

export function stopSpeaking(): void {
  if (isSpeechSupported()) window.speechSynthesis.cancel();
}

// 일부 브라우저는 voices 가 비동기로 로드됨
if (isSpeechSupported()) {
  window.speechSynthesis.onvoiceschanged = () => {
    koVoice = pickKoreanVoice();
  };
}
