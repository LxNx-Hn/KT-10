import KakaoLoginButton from '@/components/KakaoLoginButton';
import ProfilePreferences from '@/components/ProfilePreferences';
import AdminReviewLink from '@/admin/AdminReviewLink';

type SettingsPanelProps = {
  largeUi: boolean;
  onToggleLargeUi: () => void;
};

/** 로그인·큰 글씨·이동지원 안내를 담는 설정 본문 (전역 설정 drawer에서 사용). */
export default function SettingsPanel({
  largeUi,
  onToggleLargeUi,
}: SettingsPanelProps) {
  return (
    <section className="map-first__settings" aria-label="로그인과 개인 설정">
      <KakaoLoginButton />
      <AdminReviewLink />
      <button
        type="button"
        className={`map-first__settings-large${
          largeUi ? ' map-first__settings-large--active' : ''
        }`}
        aria-pressed={largeUi}
        onClick={onToggleLargeUi}
      >
        {largeUi ? '기본 글씨로 보기' : '큰 글씨와 큰 버튼 사용'}
      </button>
      <ProfilePreferences />
    </section>
  );
}
