import KakaoLoginButton from '@/components/KakaoLoginButton';
import AccountWithdrawal from '@/components/AccountWithdrawal';
import AdminReviewLink from '@/admin/AdminReviewLink';

type SettingsPanelProps = {
  largeUi: boolean;
  onToggleLargeUi: () => void;
};

/** 로그인·큰 글씨 설정 본문 (전역 설정 drawer에서 사용). */
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
      <section className="map-first__legal-notice" aria-labelledby="settings-legal-heading">
        <h3 id="settings-legal-heading" className="map-first__legal-notice-title">
          법적 고지
        </h3>
        <ul className="map-first__legal-notice-list">
          <li>
            <a className="map-first__legal-notice-row" href="/terms">
              <span>이용약관</span>
              <span className="map-first__legal-notice-chevron" aria-hidden="true">
                ›
              </span>
            </a>
          </li>
          <li>
            <a className="map-first__legal-notice-row" href="/privacy">
              <span>개인정보처리방침</span>
              <span className="map-first__legal-notice-chevron" aria-hidden="true">
                ›
              </span>
            </a>
          </li>
        </ul>
      </section>
      <AccountWithdrawal />
    </section>
  );
}
