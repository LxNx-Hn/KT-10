import { useVoiceChatStore } from '@/chat/voiceChatStore';

/** 추천 음성 명령 예시 카드. 클릭하면 마이크 없이도 챗봇으로 전달된다. */
const EXAMPLES = [
  '서면역까지 가는 길 찾아줘',
  '고령자 기준으로 알려줘',
  '임산부 기준으로 알려줘',
  '장애인 기준으로 계단 없는 길',
  '유아차로 환승 적은 길',
  '저상버스 우선으로 찾아줘',
  '그늘 많은 길로 알려줘',
];

export default function SuggestedVoiceCommands() {
  const handleUserInput = useVoiceChatStore((s) => s.handleUserInput);
  const status = useVoiceChatStore((s) => s.status);
  const busy = status === 'listening' || status === 'thinking' || status === 'speaking';

  return (
    <section className="suggest" aria-label="추천 음성 명령">
      <h2 className="section-title">이렇게 말해보세요</h2>
      <div className="suggest__grid">
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            type="button"
            className="suggest__chip"
            disabled={busy}
            onClick={() => void handleUserInput(ex)}
          >
            “{ex}”
          </button>
        ))}
      </div>
    </section>
  );
}
