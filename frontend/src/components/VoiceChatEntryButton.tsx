import { useVoiceChatStore } from '@/chat/voiceChatStore';
import { isVoiceInputSupported } from '@/chat/useSpeechRecognition';
import { primeSpeechOutput } from '@/voice/synthesis';

/** 홈 화면의 큰 마이크 버튼. 누르면 하단 챗봇이 듣기를 시작한다(요구사항 §2·§10). */
export default function VoiceChatEntryButton() {
  const requestListen = useVoiceChatStore((s) => s.requestListen);
  const status = useVoiceChatStore((s) => s.status);
  const supported = isVoiceInputSupported();
  const busy = status === 'listening' || status === 'thinking' || status === 'speaking';

  return (
    <button
      type="button"
      className="voice-entry"
      onClick={() => {
        primeSpeechOutput();
        requestListen();
      }}
      disabled={!supported || busy}
      aria-label="음성으로 길찾기"
    >
      <span className="voice-entry__mic" aria-hidden="true">🎤</span>
      <span className="voice-entry__label">
        {!supported
          ? '이 브라우저는 음성 입력 미지원'
          : busy
            ? '음성 요청 처리 중'
            : '음성으로 길찾기'}
      </span>
      <span className="voice-entry__hint">
        {busy ? '현재 요청을 마치면 다시 사용할 수 있어요' : '버튼을 누르고 목적지를 말해보세요'}
      </span>
    </button>
  );
}
