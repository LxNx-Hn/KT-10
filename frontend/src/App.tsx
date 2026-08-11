import { useState } from 'react';
import { startKakaoLogin } from '@/auth/api';
import VoiceChatDock from '@/components/VoiceChatDock';
import MobileStartupScreen, {
  hasCompletedMobileStartup,
  rememberMobileStartup,
} from '@/components/MobileStartupScreen';
import MapFirstApp from '@/v2/MapFirstApp';
import AdminReviewsPage from '@/admin/AdminReviewsPage';

/** v2 지도 중심 UI가 프로덕션 기능을 담는 단일 진입점이다. */
export default function App() {
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [startupSeen, setStartupSeen] = useState(hasCompletedMobileStartup);

  const completeStartup = () => {
    rememberMobileStartup();
    setStartupSeen(true);
  };

  if (window.location.pathname === '/admin/reviews') {
    return <AdminReviewsPage />;
  }

  if (!startupSeen) {
    return (
      <MobileStartupScreen
        onStart={completeStartup}
        onKakaoLogin={() => {
          completeStartup();
          startKakaoLogin();
        }}
      />
    );
  }

  return (
    <>
      <a className="skip-link map-first__skip" href="#main-content">
        본문으로 바로가기
      </a>
      <MapFirstApp voiceOpen={voiceOpen} />
      <VoiceChatDock
        variant="map-first"
        open={voiceOpen}
        onOpenChange={setVoiceOpen}
      />
    </>
  );
}
