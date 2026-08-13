import './mobile-startup.css';

export const MOBILE_STARTUP_STORAGE_KEY = 'dongnet.startup.seen.v1';

/** 저장소가 차단돼도 앱 진입 자체는 막지 않는다. */
export function hasCompletedMobileStartup(): boolean {
  if (typeof window === 'undefined') return true;
  try {
    return window.localStorage.getItem(MOBILE_STARTUP_STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

/** 첫 안내 완료는 기기별 localStorage에만 기록하며 개인정보는 저장하지 않는다. */
export function rememberMobileStartup(): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(MOBILE_STARTUP_STORAGE_KEY, '1');
  } catch {
    // 저장이 차단된 환경에서도 현재 세션의 시작 버튼 동작은 계속한다.
  }
}

type MobileStartupScreenProps = {
  onStart: () => void;
  onKakaoLogin: () => void;
};

const GUIDE_STEPS = [
  {
    number: '1',
    title: '출발지와 도착지 검색',
    description: '가고 싶은 장소를 입력해요.',
  },
  {
    number: '2',
    title: '이동 프로필 선택',
    description: '나에게 필요한 이동 조건을 골라요.',
  },
  {
    number: '3',
    title: '추천 경로 비교',
    description: '시간과 편의 정보를 한눈에 확인해요.',
  },
] as const;

/** MOB-18: 모바일 첫 방문자에게만 노출하는 단일 온보딩 화면. */
export default function MobileStartupScreen({
  onStart,
  onKakaoLogin,
}: MobileStartupScreenProps) {
  return (
    <main className="mobile-startup" id="main-content">
      <div className="mobile-startup__frame">
        <header className="mobile-startup__brand" aria-label="동넷">
          <img src="/favicon.svg" alt="" width="56" height="56" />
          <strong>동넷</strong>
          <span>모두의 이동을 잇는 길</span>
        </header>

        <section className="mobile-startup__intro" aria-labelledby="startup-title">
          <p className="mobile-startup__eyebrow">부산 맞춤형 접근성 길찾기</p>
          <h1 id="startup-title">나에게 맞는 길을<br />더 편하게 찾아보세요</h1>
          <p className="mobile-startup__summary">
            이동 프로필과 상황을 반영해 이용하기 편한 경로를 비교해 드려요.
          </p>
        </section>

        <ol className="mobile-startup__guide" aria-label="동넷 이용 방법">
          {GUIDE_STEPS.map((step) => (
            <li key={step.number}>
              <span className="mobile-startup__step-number" aria-hidden="true">
                {step.number}
              </span>
              <span>
                <strong>{step.title}</strong>
                <small>{step.description}</small>
              </span>
            </li>
          ))}
        </ol>

        <div className="mobile-startup__actions">
          <button
            type="button"
            className="mobile-startup__start"
            onClick={onStart}
          >
            로그인 없이 시작하기
          </button>
          <p>지도와 기본 길찾기는 로그인 없이 바로 이용할 수 있어요.</p>
        </div>

        <footer className="mobile-startup__login">
          <div>
            <strong>내 설정을 저장하고 싶다면</strong>
            <span>카카오 로그인은 프로필·이동 설정 저장을 위한 선택 기능이에요.</span>
          </div>
          <button
            type="button"
            className="btn btn--kakao mobile-startup__kakao"
            onClick={onKakaoLogin}
          >
            카카오 로그인
          </button>
        </footer>

        <nav className="mobile-startup__legal" aria-label="법적 고지">
          <a href="/terms">이용약관</a>
          <span aria-hidden="true">·</span>
          <a href="/privacy">개인정보처리방침</a>
        </nav>
      </div>
    </main>
  );
}
