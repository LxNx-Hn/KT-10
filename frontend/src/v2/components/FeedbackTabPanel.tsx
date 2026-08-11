import { useEffect, useState } from 'react';
import { resolveCurrentAuth, startKakaoLogin, type ResolvedAuth } from '@/auth/api';
import FacilityReport from '@/components/FacilityReport';
import RouteFeedback from '@/components/RouteFeedback';

type AuthView = 'loading' | ResolvedAuth['status'];

/** 후기·신고 탭: 비로그인 CTA는 한 번만, 로그인 후 각 기능을 분리 표시한다. */
export default function FeedbackTabPanel({
  selectedRouteId,
}: {
  selectedRouteId: string | null;
}) {
  const [authView, setAuthView] = useState<AuthView>('loading');

  useEffect(() => {
    let cancelled = false;
    void resolveCurrentAuth().then((resolved) => {
      if (!cancelled) setAuthView(resolved.status);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (authView === 'loading') {
    return (
      <p className="map-first__feedback-login-note" role="status" aria-live="polite">
        로그인 상태를 확인하는 중입니다.
      </p>
    );
  }

  if (authView === 'unavailable') {
    return (
      <p className="map-first__feedback-login-note" role="status" aria-live="polite">
        지금은 로그인 상태를 확인하기 어렵습니다. 잠시 후 다시 시도해 주세요.
      </p>
    );
  }

  if (authView === 'guest') {
    return (
      <div className="map-first__feedback-login" aria-label="후기·신고 로그인 안내">
        <p className="map-first__feedback-login-note">
          후기와 신고 기능을 이용하려면 카카오 로그인이 필요해요.
        </p>
        <button
          type="button"
          className="btn btn--kakao map-first__feedback-login-cta"
          onClick={startKakaoLogin}
        >
          카카오 로그인
        </button>
      </div>
    );
  }

  return (
    <div className="map-first__feedback-tab">
      <RouteFeedback
        key={selectedRouteId ?? 'no-route'}
        authStatus="authenticated"
        hideGuestPrompt
      />
      <FacilityReport authStatus="authenticated" hideGuestPrompt />
    </div>
  );
}
