import { useState } from 'react';
import { startKakaoLogin } from '@/auth/api';
import SignupConsentPage from '@/auth/SignupConsentPage';
import AccountDeletionPage from '@/auth/AccountDeletionPage';
import MobileStartupScreen, {
  hasCompletedMobileStartup,
  rememberMobileStartup,
} from '@/components/MobileStartupScreen';
import MapFirstApp from '@/v2/MapFirstApp';
import AdminReviewsPage from '@/admin/AdminReviewsPage';
import LegalDocumentPage from '@/legal/LegalDocumentPage';

/** v2 지도 중심 UI가 프로덕션 기능을 담는 단일 진입점이다. */
export default function App() {
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [startupSeen, setStartupSeen] = useState(hasCompletedMobileStartup);
  const pathname = window.location.pathname;

  const completeStartup = () => {
    rememberMobileStartup();
    setStartupSeen(true);
  };

  // 공개 법적 문서와 가입 수락은 startup·로그인 여부와 무관하게 최우선 분기한다.
  if (pathname === '/terms') {
    return <LegalDocumentPage documentId="terms" />;
  }
  if (pathname === '/privacy') {
    return <LegalDocumentPage documentId="privacy" />;
  }
  if (pathname === '/account-deletion') {
    return <AccountDeletionPage />;
  }
  if (pathname === '/signup/consent') {
    return <SignupConsentPage />;
  }

  if (pathname === '/admin/reviews') {
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
      <MapFirstApp
        voiceOpen={voiceOpen}
        onVoiceOpenChange={setVoiceOpen}
      />
    </>
  );
}
