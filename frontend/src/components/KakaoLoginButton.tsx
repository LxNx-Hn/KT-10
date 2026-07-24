import { useEffect, useState } from 'react';
import { getCurrentUser, logout, startKakaoLogin, type CurrentUser } from '@/auth/api';
import { useAppStore } from '@/store/appStore';

export default function KakaoLoginButton() {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);
  const [logoutFailed, setLogoutFailed] = useState(false);
  const setProfile = useAppStore((state) => state.setProfile);

  useEffect(() => {
    void getCurrentUser().then((current) => {
      setUser(current);
      const storedProfile = current?.preference.profile;
      if (storedProfile) setProfile(storedProfile);
    }).catch(() => setUser(null));
  }, [setProfile]);

  if (!user) {
    return <button type="button" className="btn btn--ghost" onClick={startKakaoLogin}>카카오 로그인</button>;
  }
  return (
    <button
      type="button"
      className="btn btn--ghost"
      disabled={loggingOut}
      onClick={() => {
        setLoggingOut(true);
        setLogoutFailed(false);
        void logout()
          .then(() => setUser(null))
          .catch(() => setLogoutFailed(true))
          .finally(() => setLoggingOut(false));
      }}
    >
      {loggingOut
        ? '로그아웃 중…'
        : logoutFailed
          ? '로그아웃 재시도'
          : `${user.nickname || '카카오 사용자'} · 로그아웃`}
    </button>
  );
}
