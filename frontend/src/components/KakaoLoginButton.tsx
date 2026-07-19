import { startKakaoLogin } from '@/auth/api';

export default function KakaoLoginButton() {
  return <button type="button" className="btn btn--ghost" onClick={startKakaoLogin}>카카오 로그인</button>;
}
