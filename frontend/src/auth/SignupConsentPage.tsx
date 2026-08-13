import { useCallback, useEffect, useId, useState } from 'react';
import { ApiError, toUserMessage } from '@/api/http';
import {
  cancelSignup,
  completeSignup,
  resolveSignupStatus,
  startKakaoLogin,
  type ResolvedSignupStatus,
} from '@/auth/api';
import './signup-consent.css';

type ConsentView = 'loading' | 'form' | 'expired' | 'unavailable';

function viewFromSignupStatus(
  status: ResolvedSignupStatus['status'],
): Exclude<ConsentView, 'loading'> {
  if (status === 'pending') return 'form';
  if (status === 'unavailable') return 'unavailable';
  return 'expired';
}

/** 카카오 OAuth 이후 이용약관 수락을 받는 가입 완료 화면. */
export default function SignupConsentPage() {
  const termsId = useId();
  const [view, setView] = useState<ConsentView>('loading');
  const [accepted, setAccepted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState('');

  const checkSignupStatus = useCallback(() => {
    setView('loading');
    void resolveSignupStatus().then((resolved) => {
      setView(viewFromSignupStatus(resolved.status));
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    void resolveSignupStatus().then((resolved) => {
      if (cancelled) return;
      setView(viewFromSignupStatus(resolved.status));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function onSubmit() {
    if (!accepted || submitting) return;
    setSubmitting(true);
    setError('');
    try {
      await completeSignup();
      window.location.assign('/');
    } catch (cause) {
      if (cause instanceof ApiError && (cause.status === 410 || cause.status === 401)) {
        setView('expired');
        setSubmitting(false);
        return;
      }
      setError(
        toUserMessage(
          cause,
          '가입을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.',
        ),
      );
      setSubmitting(false);
    }
  }

  async function onCancel() {
    if (cancelling) return;
    setCancelling(true);
    try {
      await cancelSignup();
    } catch {
      // 만료·네트워크 실패여도 홈으로 보낸다. 민감 오류는 노출하지 않는다.
    }
    window.location.assign('/');
  }

  if (view === 'loading') {
    return (
      <div className="signup-consent signup-consent--compact">
        <main className="signup-consent__main" id="main-content">
          <h1>동넷 시작하기</h1>
          <p className="signup-consent__lead">가입 정보를 확인하고 있습니다.</p>
        </main>
      </div>
    );
  }

  if (view === 'unavailable') {
    return (
      <div className="signup-consent">
        <main className="signup-consent__main" id="main-content">
          <h1>동넷 시작하기</h1>
          <p className="signup-consent__lead">
            가입 정보를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.
          </p>
          <div className="signup-consent__actions">
            <button
              type="button"
              className="signup-consent__submit"
              onClick={checkSignupStatus}
            >
              다시 확인
            </button>
            <button
              type="button"
              className="btn btn--kakao signup-consent__submit"
              onClick={startKakaoLogin}
            >
              카카오 로그인 다시 하기
            </button>
            <button
              type="button"
              className="signup-consent__cancel"
              onClick={() => window.location.assign('/')}
            >
              동넷으로 돌아가기
            </button>
          </div>
        </main>
      </div>
    );
  }

  if (view === 'expired') {
    return (
      <div className="signup-consent signup-consent--compact">
        <main className="signup-consent__main" id="main-content">
          <h1>동넷 시작하기</h1>
          <p className="signup-consent__lead">
            가입 정보가 만료되었습니다. 카카오 로그인을 다시 진행해 주세요.
          </p>
          <div className="signup-consent__actions">
            <button
              type="button"
              className="btn btn--kakao signup-consent__submit"
              onClick={startKakaoLogin}
            >
              카카오 로그인 다시 하기
            </button>
            <button
              type="button"
              className="signup-consent__cancel"
              onClick={() => window.location.assign('/')}
            >
              동넷으로 돌아가기
            </button>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="signup-consent">
      <main className="signup-consent__main" id="main-content">
        <h1>동넷 시작하기</h1>
        <p className="signup-consent__lead">
          카카오 계정으로 동넷을 시작합니다. 서비스 이용을 위해 아래 내용을
          확인해 주세요.
        </p>

        <div className="signup-consent__terms">
          <input
            id={termsId}
            type="checkbox"
            checked={accepted}
            onChange={(event) => setAccepted(event.target.checked)}
          />
          <label htmlFor={termsId}>
            <span className="signup-consent__required">[필수]</span>
            {' '}
            이용약관에 동의합니다.
          </label>
          <a href="/terms" className="signup-consent__doc-link">보기</a>
        </div>

        <section className="signup-consent__privacy" aria-labelledby="signup-privacy-heading">
          <h2 id="signup-privacy-heading">개인정보처리방침</h2>
          <p>
            카카오 로그인과 동넷 이용 과정에서 처리되는 개인정보 내용을 확인할
            수 있습니다.
          </p>
          <a href="/privacy" className="signup-consent__doc-link">보기</a>
        </section>

        {error ? (
          <p className="signup-consent__error" role="alert" aria-live="polite">
            {error}
          </p>
        ) : null}

        <div className="signup-consent__actions">
          <button
            type="button"
            className="signup-consent__submit"
            disabled={!accepted || submitting}
            onClick={() => void onSubmit()}
          >
            {submitting ? '처리 중…' : '동의하고 시작하기'}
          </button>
          <button
            type="button"
            className="signup-consent__cancel"
            disabled={cancelling}
            onClick={() => void onCancel()}
          >
            취소
          </button>
        </div>
      </main>
    </div>
  );
}
