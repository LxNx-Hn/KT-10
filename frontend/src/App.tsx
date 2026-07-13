import { useEffect, useRef } from 'react';
import { useAppStore } from '@/store/appStore';
import { DISTRICT } from '@/config/district';
import SearchHome from '@/components/SearchHome';
import RouteResultSection from '@/components/RouteResultSection';
import MapPreviewSection from '@/components/MapPreviewSection';
import VoiceChatDock from '@/components/VoiceChatDock';
import KakaoLoginButton from '@/components/KakaoLoginButton';

/**
 * 정보 구조(요구사항 §1·§3):
 *   SearchHome(검색 중심) → RouteResultSection(경로 카드 우선) → MapPreviewSection(지도 보조)
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
      resultsRef.current.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
    }
    if (!hasResults) scrolled.current = false;
  }, [hasResults]);

  return (
    <div className={`app ${largeUi ? 'app--large' : ''}`} data-profile={profile}>
      <header className="app__header">
        <div>
          <p className="app__eyebrow">서비스명 미정</p>
          <h1 className="app__title">접근성 경로 추천</h1>
          <p className="app__subtitle">{DISTRICT.name} · 보행·대중교통 중심 데모</p>
        </div>
        <button
          type="button"
          className="btn btn--ghost app__largebtn"
          aria-pressed={largeUi}
          onClick={toggleLargeUi}
        >
          {largeUi ? '큰 글씨 ON' : '큰 글씨 OFF'}
        </button>
        <KakaoLoginButton />
      </header>

      <main className="app__main">
        <SearchHome />
        <div ref={resultsRef}>
          <RouteResultSection />
        </div>
        <MapPreviewSection />
      </main>

      <VoiceChatDock />
    </div>
  );
}
