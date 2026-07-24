import { useEffect, useRef, useState } from 'react';
import { useVoiceChatStore } from '@/chat/voiceChatStore';
import { useSpeechRecognition } from '@/chat/useSpeechRecognition';
import { stopSpeaking } from '@/voice/synthesis';
import { PROFILE_LIST } from '@/config/profiles';
import type { VoiceChatStatus } from '@/voice/intents';

const STATUS_LABEL: Record<VoiceChatStatus, string> = {
  idle: '대기 중',
  listening: '듣는 중입니다…',
  thinking: '분석 중입니다…',
  speaking: '안내 중입니다…',
  error: '오류가 발생했어요',
};

/** 하단 고정 실시간 음성 챗봇 패널 (요구사항 §7) */
export default function VoiceChatDock({
  variant = 'dock',
}: {
  variant?: 'dock' | 'map-first';
}) {
  const status = useVoiceChatStore((s) => s.status);
  const messages = useVoiceChatStore((s) => s.messages);
  const interim = useVoiceChatStore((s) => s.interim);
  const awaiting = useVoiceChatStore((s) => s.awaiting);
  const listenRequestId = useVoiceChatStore((s) => s.listenRequestId);
  const handleUserInput = useVoiceChatStore((s) => s.handleUserInput);
  const repeatLast = useVoiceChatStore((s) => s.repeatLast);
  const setStatus = useVoiceChatStore((s) => s.setStatus);

  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);

  const { supported, listening, start, stop } = useSpeechRecognition({
    onStart: () => useVoiceChatStore.getState().setStatus('listening'),
    onInterim: (t) => useVoiceChatStore.getState().setInterim(t),
    onFinal: (t) => void handleUserInput(t),
    onEnd: () => {
      const s = useVoiceChatStore.getState();
      if (s.status === 'listening') s.setStatus('idle');
      s.setInterim('');
    },
    onError: () => useVoiceChatStore.getState().setStatus('error'),
  });
  const processing = status === 'thinking';
  const voiceBusy = status === 'thinking' || status === 'speaking';

  // 외부(홈 마이크 버튼)에서 듣기 요청 시 시작
  useEffect(() => {
    if (listenRequestId > 0) {
      setOpen(true);
      start();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listenRequestId]);

  // 새 메시지 시 스크롤 하단 고정
  useEffect(() => {
    scrollRef.current?.scrollTo?.({ top: scrollRef.current.scrollHeight });
  }, [messages, interim]);

  const submitText = () => {
    const t = draft.trim();
    if (!t) return;
    setDraft('');
    void handleUserInput(t);
  };

  if (variant === 'map-first' && !open) {
    return null;
  }

  return (
    <div
      className={variant === 'map-first' ? 'voicedock voicedock--map-first' : 'voicedock'}
      role="region"
      aria-label="음성 챗봇"
    >
      {variant === 'map-first' ? (
        <button
          type="button"
          className="voicedock__handle"
          aria-expanded={open}
          aria-label="음성 챗봇 닫기"
          onClick={() => {
            if (listening) stop();
            stopSpeaking();
            if (status === 'listening' || status === 'speaking') setStatus('idle');
            setOpen(false);
          }}
        >
          <span className={`voicedock__dot voicedock__dot--${status}`} aria-hidden="true" />
          음성 챗봇 · {STATUS_LABEL[status]} · 닫기 ✕
        </button>
      ) : (
        <button
          type="button"
          className="voicedock__handle"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          <span className={`voicedock__dot voicedock__dot--${status}`} aria-hidden="true" />
          음성 챗봇 · {STATUS_LABEL[status]} {open ? '▾' : '▴'}
        </button>
      )}

      {open && (
        <div className="voicedock__body">
          <div className="voicedock__log" ref={scrollRef} aria-live="polite">
            {messages.map((m) => (
              <div key={m.id} className={`chatmsg chatmsg--${m.role}`}>
                <span className="chatmsg__who">
                  {m.role === 'user' ? '나' : m.role === 'assistant' ? '챗봇' : '안내'}
                </span>
                <p className="chatmsg__text">{m.text}</p>
              </div>
            ))}
            {interim && (
              <div className="chatmsg chatmsg--user chatmsg--interim">
                <span className="chatmsg__who">나</span>
                <p className="chatmsg__text">{interim}…</p>
              </div>
            )}
          </div>

          {/* 추가 질문(프로필) 대기 시 빠른 선택 칩 */}
          {awaiting === 'profile' && (
            <div className="voicedock__quick" role="group" aria-label="프로필 빠른 선택">
              {PROFILE_LIST.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className="chip chip--small"
                  disabled={processing}
                  onClick={() => void handleUserInput(`${p.label} 기준으로 알려줘`)}
                >
                  {p.label}
                </button>
              ))}
            </div>
          )}

          <div className="voicedock__controls">
            <button
              type="button"
              className={`voice-fab ${listening ? 'voice-fab--on' : ''}`}
              onClick={listening ? stop : start}
              disabled={!supported || voiceBusy}
              aria-pressed={listening}
              aria-label={listening ? '음성 인식 중지' : '음성 말하기'}
            >
              🎤 {supported ? (listening ? '듣는 중' : '말하기') : '음성 미지원'}
            </button>
            <button
              type="button"
              className="btn btn--repeat"
              onClick={repeatLast}
              disabled={status === 'thinking' || status === 'listening'}
              aria-label="다시 듣기"
            >
              🔁 다시 듣기
            </button>
            <button
              type="button"
              className="btn btn--stop"
              onClick={() => {
                stopSpeaking();
                setStatus('idle');
              }}
              disabled={status !== 'speaking'}
              aria-label="음성 정지"
            >
              ⏹
            </button>
          </div>

          {/* 텍스트 입력 대체 수단(요구사항 §7) */}
          <form
            className="voicedock__textentry"
            onSubmit={(e) => {
              e.preventDefault();
              submitText();
            }}
          >
            <input
              type="text"
              value={draft}
              placeholder="음성 대신 입력해도 됩니다 (예: 서면역까지 가는 길 찾아줘)"
              onChange={(e) => setDraft(e.target.value)}
              aria-label="챗봇 텍스트 입력"
              aria-busy={processing}
            />
            <button
              type="submit"
              className="btn btn--primary"
              disabled={!draft.trim() || processing}
            >
              {processing ? '처리 중' : '보내기'}
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
