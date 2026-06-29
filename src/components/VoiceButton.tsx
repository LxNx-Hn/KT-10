import { useAppStore } from '@/store/appStore';
import { useVoiceControl } from '@/voice/useVoiceControl';
import { speak, stopSpeaking } from '@/voice/synthesis';

/** 화면 하단 고정 음성명령 버튼 + 다시 듣기(기획서 §12) */
export default function VoiceButton() {
  const { supported, listening, transcript, start, stop } = useVoiceControl();
  const lastSpoken = useAppStore((s) => s.lastSpoken);

  return (
    <div className="voicebar" role="region" aria-label="음성 조작">
      {transcript && (
        <p className="voicebar__transcript" aria-live="polite">
          “{transcript}”
        </p>
      )}
      <div className="voicebar__buttons">
        <button
          type="button"
          className={`voice-fab ${listening ? 'voice-fab--on' : ''}`}
          onClick={listening ? stop : start}
          disabled={!supported}
          aria-pressed={listening}
          aria-label={listening ? '음성 인식 중지' : '음성명령 시작'}
        >
          🎤 {supported ? (listening ? '듣는 중…' : '음성명령') : '음성 미지원'}
        </button>
        <button
          type="button"
          className="btn btn--repeat"
          onClick={() => (lastSpoken ? speak(lastSpoken) : undefined)}
          aria-label="마지막 안내 다시 듣기"
        >
          🔁 다시 듣기
        </button>
        <button
          type="button"
          className="btn btn--stop"
          onClick={stopSpeaking}
          aria-label="음성안내 정지"
        >
          ⏹ 정지
        </button>
      </div>
    </div>
  );
}
