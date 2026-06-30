import { useVoiceChatStore } from '@/chat/voiceChatStore';
import { isVoiceInputSupported } from '@/chat/useSpeechRecognition';

/** 홈 화면의 큰 마이크 버튼. 누르면 하단 챗봇이 듣기를 시작한다(요구사항 §2·§10). */
export default function VoiceChatEntryButton() {
  const requestListen = useVoiceChatStore((s) => s.requestListen);
  const supported = isVoiceInputSupported();

  return (
    <button
      type="button"
      className="voice-entry"
      onClick={requestListen}
      disabled={!supported}
      aria-label="음성으로 길찾기"
    >
      <span className="voice-entry__mic" aria-hidden="true">🎤</span>
      <span className="voice-entry__label">
        {supported ? '음성으로 길찾기' : '이 브라우저는 음성 입력 미지원'}
      </span>
      <span className="voice-entry__hint">버튼을 누르고 목적지를 말해보세요</span>
    </button>
  );
}
