import { useCallback, useEffect, useState } from 'react';
import { ApiError } from '@/api/http';
import {
  cancelExternalAccountDeletion,
  confirmExternalAccountDeletion,
  resolveAccountDeletionStatus,
  resolveDeletionPageAuth,
  startAccountDeletionVerification,
  withdraw,
} from '@/auth/api';
import {
  WITHDRAW_INFO,
  WITHDRAW_WARNING,
} from '@/components/AccountWithdrawal';
import './account-deletion.css';

type DeletionView =
  | 'loading'
  | 'guest'
  | 'confirm'
  | 'conflict'
  | 'not-found'
  | 'expired'
  | 'unavailable'
  | 'completed';

type ConfirmSource = 'session' | 'verified';

function notFoundQuery(): boolean {
  return new URLSearchParams(window.location.search).get('result') === 'not-found';
}

/** Google Play 외부 계정 삭제. 가입·약관·세션 발급과 분리한다. */
export default function AccountDeletionPage() {
  const [view, setView] = useState<DeletionView>('loading');
  const [confirmSource, setConfirmSource] = useState<ConfirmSource>('verified');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const loadStatus = useCallback(() => {
    setView('loading');
    setError('');
    void Promise.all([
      resolveDeletionPageAuth(),
      resolveAccountDeletionStatus(),
    ]).then(([auth, deletion]) => {
      if (auth.status === 'unavailable' || deletion.status === 'unavailable') {
        setView('unavailable');
        return;
      }
      if (auth.status === 'authenticated' && deletion.status === 'verified') {
        setView('conflict');
        return;
      }
      if (auth.status === 'authenticated') {
        setConfirmSource('session');
        setView('confirm');
        return;
      }
      if (deletion.status === 'verified') {
        setConfirmSource('verified');
        setView('confirm');
        return;
      }
      setView(notFoundQuery() ? 'not-found' : 'guest');
    });
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  async function onConfirm() {
    if (submitting) return;
    setSubmitting(true);
    setError('');
    try {
      if (confirmSource === 'session') {
        await withdraw();
      } else {
        await confirmExternalAccountDeletion();
      }
      setView('completed');
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        setError(
          '관리자 계정은 탈퇴할 수 없습니다. 관리자 권한을 해제한 뒤 다시 시도해 주세요.',
        );
        setSubmitting(false);
        return;
      }
      if (cause instanceof ApiError && (cause.status === 410 || cause.status === 401)) {
        setView('expired');
        setSubmitting(false);
        return;
      }
      setError('회원 탈퇴를 완료하지 못했습니다. 다시 시도해 주세요.');
      setSubmitting(false);
    }
  }

  async function onLeave() {
    if (confirmSource === 'verified') {
      try {
        await cancelExternalAccountDeletion();
      } catch {
        // 홈으로 보내는 취소를 네트워크가 막지 않는다.
      }
    }
    window.location.assign('/');
  }

  if (view === 'loading') {
    return (
      <div className="account-deletion account-deletion--compact">
        <main className="account-deletion__main" id="main-content">
          <h1>동넷 계정 삭제</h1>
          <p className="account-deletion__lead">계정 삭제 상태를 확인하고 있습니다.</p>
        </main>
      </div>
    );
  }

  if (view === 'conflict') {
    return (
      <div className="account-deletion account-deletion--compact">
        <main className="account-deletion__main" id="main-content">
          <h1>동넷 계정 삭제</h1>
          <p className="account-deletion__lead" role="alert">
            본인 확인 상태가 변경되었습니다.
            안전을 위해 계정 삭제를 다시 시작해 주세요.
          </p>
          <div className="account-deletion__actions">
            <button
              type="button"
              className="btn btn--kakao account-deletion__submit"
              onClick={startAccountDeletionVerification}
            >
              카카오로 본인 확인
            </button>
            <button
              type="button"
              className="account-deletion__cancel"
              onClick={() => window.location.assign('/')}
            >
              동넷으로 돌아가기
            </button>
          </div>
        </main>
      </div>
    );
  }

  if (view === 'unavailable') {
    return (
      <div className="account-deletion account-deletion--compact">
        <main className="account-deletion__main" id="main-content">
          <h1>동넷 계정 삭제</h1>
          <p className="account-deletion__lead">
            계정 삭제 상태를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.
          </p>
          <div className="account-deletion__actions">
            <button
              type="button"
              className="account-deletion__submit"
              onClick={loadStatus}
            >
              다시 확인
            </button>
            <button
              type="button"
              className="account-deletion__cancel"
              onClick={() => window.location.assign('/')}
            >
              동넷으로 돌아가기
            </button>
          </div>
        </main>
      </div>
    );
  }

  if (view === 'not-found') {
    return (
      <div className="account-deletion account-deletion--compact">
        <main className="account-deletion__main" id="main-content">
          <h1>동넷 계정 삭제</h1>
          <p className="account-deletion__lead">
            삭제할 동넷 계정을 찾을 수 없습니다.
          </p>
          <div className="account-deletion__actions">
            <button
              type="button"
              className="account-deletion__cancel"
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
      <div className="account-deletion account-deletion--compact">
        <main className="account-deletion__main" id="main-content">
          <h1>동넷 계정 삭제</h1>
          <p className="account-deletion__lead">
            본인 확인 정보가 만료되었습니다. 카카오 본인 확인을 다시 진행해 주세요.
          </p>
          <div className="account-deletion__actions">
            <button
              type="button"
              className="btn btn--kakao account-deletion__submit"
              onClick={startAccountDeletionVerification}
            >
              카카오로 본인 확인
            </button>
            <button
              type="button"
              className="account-deletion__cancel"
              onClick={() => window.location.assign('/')}
            >
              동넷으로 돌아가기
            </button>
          </div>
        </main>
      </div>
    );
  }

  if (view === 'completed') {
    return (
      <div className="account-deletion account-deletion--compact">
        <main className="account-deletion__main" id="main-content">
          <h1>동넷 계정 삭제</h1>
          <p className="account-deletion__lead" role="status" aria-live="polite">
            회원 탈퇴가 완료되었습니다.
          </p>
          <div className="account-deletion__actions">
            <button
              type="button"
              className="account-deletion__submit"
              onClick={() => window.location.assign('/')}
            >
              동넷으로 돌아가기
            </button>
          </div>
        </main>
      </div>
    );
  }

  if (view === 'guest') {
    return (
      <div className="account-deletion account-deletion--compact">
        <main className="account-deletion__main" id="main-content">
          <h1>동넷 계정 삭제</h1>
          <p className="account-deletion__lead">
            동넷 계정과 서비스 이용 데이터를 삭제하려면 카카오 계정으로 본인
            확인이 필요합니다. 앱을 설치하지 않아도 이 페이지에서 진행할 수
            있습니다.
          </p>
          <div className="account-deletion__actions">
            <button
              type="button"
              className="btn btn--kakao account-deletion__submit"
              onClick={startAccountDeletionVerification}
            >
              카카오로 본인 확인
            </button>
            <button
              type="button"
              className="account-deletion__cancel"
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
    <div className="account-deletion">
      <main className="account-deletion__main" id="main-content">
        <h1>동넷 계정 삭제</h1>
        <p className="account-deletion__lead">
          탈퇴하면 아래 내용이 적용됩니다. 이 페이지를 연 것만으로 계정이
          삭제되지는 않습니다.
        </p>
        <ul className="account-deletion__info">
          {WITHDRAW_INFO.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
        <p className="account-deletion__warning" role="note">
          {WITHDRAW_WARNING}
        </p>
        {error ? (
          <p className="account-deletion__error" role="alert" aria-live="polite">
            {error}
          </p>
        ) : null}
        <div className="account-deletion__actions">
          <button
            type="button"
            className="account-deletion__submit"
            disabled={submitting}
            onClick={() => void onConfirm()}
          >
            {submitting ? '탈퇴 처리 중…' : '탈퇴하기'}
          </button>
          <button
            type="button"
            className="account-deletion__cancel"
            disabled={submitting}
            onClick={() => void onLeave()}
          >
            동넷으로 돌아가기
          </button>
        </div>
      </main>
    </div>
  );
}
