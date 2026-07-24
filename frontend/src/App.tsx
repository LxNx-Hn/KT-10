import { useEffect, useRef } from 'react';
import { useAppStore } from '@/store/appStore';
import { DISTRICT } from '@/config/district';
import SearchHome from '@/components/SearchHome';
import RouteResultSection from '@/components/RouteResultSection';
import MapPreviewSection from '@/components/MapPreviewSection';
import VoiceChatDock from '@/components/VoiceChatDock';
import KakaoLoginButton from '@/components/KakaoLoginButton';
import InstallPrompt from '@/components/InstallPrompt';
import ConnectionStatus from '@/components/ConnectionStatus';
import { preferredScrollBehavior } from '@/utils/motion';

/**
 * 정보 구조(요구사항 §1·§3):
 *   SearchHome(검색 중심) → RouteResultSection(활성 지도 + 점수순 스와이프 카드)
 *   + VoiceChatDock(하단 고정 실시간 음성 챗봇)
 * 지도는 첫 화면의 중심이 아니라 검색 결과 확인용 보조 화면이다.
 */
export default function App() {
  const largeUi = useAppStore((s) => s.largeUi);
  const toggleLargeUi = useAppStore((s) => s.toggleLargeUi);
  const profile = useAppStore((s) => s.profile);
  const hasResults = useAppStore((s) => s.recommendations.length > 0);

  // 결과가 처음 생기면 결과 영역으로 부드럽게 스크롤
  const resultsRef = useRef<HTMLDivElement>(null);
  const scrolled = useRef(false);
  useEffect(() => {
    if (hasResults && !scrolled.current && resultsRef.current) {
      scrolled.current = true;
      resultsRef.current.scrollIntoView?.({
        behavior: preferredScrollBehavior(),
        block: 'start',
      });
    }
    if (!hasResults) scrolled.current = false;
  }, [hasResults]);

  return (
    <div className={`app ${largeUi ? 'app--large' : ''}`} data-profile={profile}>
      <a className="skip-link" href="#main-content">본문으로 바로가기</a>
      <header className="app__header">
        <div className="app__brand">
          <span className="app__brandmark" aria-hidden="true">길</span>
          <div>
            <p className="app__eyebrow">{DISTRICT.name}</p>
            <h1 className="app__title">접근성 길찾기</h1>
            <p className="app__subtitle">경사·그늘·이동 편의를 함께 비교합니다</p>
          </div>
        </div>
        <div className="app__header-actions">
          <ConnectionStatus />
          <button
            type="button"
            className="btn btn--header app__largebtn"
            aria-pressed={largeUi}
            onClick={toggleLargeUi}
          >
            {largeUi ? '기본 글씨' : '큰 글씨'}
          </button>
          <KakaoLoginButton />
        </div>
      </header>

      <main className="app__main" id="main-content">
        <SearchHome />
        <div ref={resultsRef}>
          <RouteResultSection />
        </div>
        {!hasResults && <MapPreviewSection />}
      </main>

      <InstallPrompt />
      <VoiceChatDock />
    </div>
  );
}
