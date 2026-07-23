import { useEffect, useState } from 'react';

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>;
}

export default function InstallPrompt() {
  const [promptEvent, setPromptEvent] = useState<BeforeInstallPromptEvent | null>(null);
  const [installed, setInstalled] = useState(false);

  useEffect(() => {
    const capture = (event: Event) => {
      event.preventDefault();
      setPromptEvent(event as BeforeInstallPromptEvent);
    };
    const complete = () => {
      setInstalled(true);
      setPromptEvent(null);
    };
    window.addEventListener('beforeinstallprompt', capture);
    window.addEventListener('appinstalled', complete);
    return () => {
      window.removeEventListener('beforeinstallprompt', capture);
      window.removeEventListener('appinstalled', complete);
    };
  }, []);

  if (!promptEvent || installed) return null;

  return (
    <aside className="install-prompt" aria-label="앱 설치 안내">
      <div>
        <strong>홈 화면에서 바로 길찾기</strong>
        <p>부산 접근성 길찾기를 앱처럼 설치할 수 있습니다.</p>
      </div>
      <button
        type="button"
        className="btn btn--primary install-prompt__button"
        onClick={() => {
          void promptEvent.prompt().then(() => promptEvent.userChoice).then(() => {
            setPromptEvent(null);
          });
        }}
      >
        설치
      </button>
      <button
        type="button"
        className="install-prompt__close"
        aria-label="설치 안내 닫기"
        onClick={() => setPromptEvent(null)}
      >
        ×
      </button>
    </aside>
  );
}
