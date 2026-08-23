import { useEffect, useId, useState } from 'react';
import {
  isIosLikePlatform,
  isPwaStandalone,
} from '@/pwa/installPlatform';

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>;
}

function readIosLike(): boolean {
  return isIosLikePlatform(
    navigator.userAgent,
    navigator.platform,
    navigator.maxTouchPoints,
  );
}

export default function InstallPrompt() {
  const stepsId = useId();
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null);
  const [installed, setInstalled] = useState(() => isPwaStandalone());
  const [iosDismissed, setIosDismissed] = useState(false);
  const [iosStepsOpen, setIosStepsOpen] = useState(false);

  const iosLike = readIosLike();
  const standalone = installed;

  useEffect(() => {
    if (iosLike) {
      setDeferredPrompt(null);
    }
  }, [iosLike]);

  useEffect(() => {
    const capture = (event: Event) => {
      if (readIosLike() || isPwaStandalone()) {
        // Chromium device emulation에서도 native install UI를 막되
        // Android deferred state는 만들지 않는다.
        event.preventDefault();
        return;
      }
      event.preventDefault();
      setDeferredPrompt(event as BeforeInstallPromptEvent);
    };
    const complete = () => {
      setInstalled(true);
      setDeferredPrompt(null);
    };
    window.addEventListener('beforeinstallprompt', capture);
    window.addEventListener('appinstalled', complete);
    return () => {
      window.removeEventListener('beforeinstallprompt', capture);
      window.removeEventListener('appinstalled', complete);
    };
  }, []);

  // platform precedence:
  // 1) standalone → null
  // 2) iOS/iPadOS → manual guide only
  // 3) non-iOS + deferredPrompt → Android install UI
  // 4) else → null
  if (standalone) return null;

  const showAndroid = !iosLike && Boolean(deferredPrompt);
  const showIos = iosLike && !iosDismissed;

  if (showAndroid && deferredPrompt) {
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
            void deferredPrompt.prompt().then(() => deferredPrompt.userChoice).then(() => {
              setDeferredPrompt(null);
            });
          }}
        >
          설치
        </button>
        <button
          type="button"
          className="install-prompt__close"
          aria-label="설치 안내 닫기"
          onClick={() => setDeferredPrompt(null)}
        >
          ×
        </button>
      </aside>
    );
  }

  if (!showIos) return null;

  return (
    <aside
      className={`install-prompt install-prompt--ios${
        iosStepsOpen ? ' install-prompt--expanded' : ''
      }`}
      aria-label="앱 설치 안내"
    >
      <div className="install-prompt__copy">
        <strong>{iosStepsOpen ? '동넷 설치하기' : '동넷을 홈 화면에 추가하세요'}</strong>
        {!iosStepsOpen ? (
          <p>앱처럼 바로 열어 더 편하게 길찾을 수 있어요.</p>
        ) : (
          <ol id={stepsId} className="install-prompt__steps">
            <li>브라우저의 공유 버튼을 눌러주세요.</li>
            <li>&quot;홈 화면에 추가&quot;를 선택하세요.</li>
            <li>오른쪽 위 &quot;추가&quot;를 눌러주세요.</li>
          </ol>
        )}
      </div>
      {!iosStepsOpen ? (
        <button
          type="button"
          className="btn btn--primary install-prompt__button"
          aria-expanded={iosStepsOpen}
          aria-controls={stepsId}
          onClick={() => setIosStepsOpen(true)}
        >
          설치 방법 보기
        </button>
      ) : null}
      <button
        type="button"
        className="install-prompt__close"
        aria-label="설치 안내 닫기"
        onClick={() => {
          setIosDismissed(true);
          setIosStepsOpen(false);
        }}
      >
        ×
      </button>
    </aside>
  );
}
