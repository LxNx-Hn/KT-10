import { useEffect, useId, useRef, useState } from 'react';
import {
  AUTH_SESSION_ENDED_EVENT,
  getCurrentUser,
  notifyAuthSessionEnded,
  withdraw,
} from '@/auth/api';
import { ApiError } from '@/api/http';

export const WITHDRAW_INFO = [
  '탈퇴하면 계정·프로필·이동 기록과 작성한 후기가 즉시 삭제됩니다.',
  '시설 신고는 작성자 정보·자유입력 내용·신고 당시 위치정보를 삭제하고 시설 관리에 필요한 정보만 보존합니다.',
  '탈퇴 처리 및 부정 이용 방지에 필요한 최소 정보는 최대 30일간 분리 보관 후 삭제됩니다.',
  '카카오 연결 끊기 실패 시 재시도를 위해 카카오 회원번호가 최대 30일간 보관될 수 있으며, 연결 끊기 성공 시 즉시 삭제됩니다.',
] as const;

export const WITHDRAW_WARNING =
  '탈퇴 후에는 복구할 수 없으며, 다시 이용하려면 새 계정으로 가입해야 합니다.';

export default function AccountWithdrawal() {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const [loggedIn, setLoggedIn] = useState(false);
  const [checking, setChecking] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [withdrawing, setWithdrawing] = useState(false);
  const [statusMessage, setStatusMessage] = useState('');

  useEffect(() => {
    let active = true;
    void getCurrentUser()
      .then((user) => {
        if (active) setLoggedIn(Boolean(user));
      })
      .catch(() => {
        if (active) setLoggedIn(false);
      })
      .finally(() => {
        if (active) setChecking(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const syncLoggedIn = () => setLoggedIn(false);
    window.addEventListener(AUTH_SESSION_ENDED_EVENT, syncLoggedIn);
    return () => window.removeEventListener(AUTH_SESSION_ENDED_EVENT, syncLoggedIn);
  }, []);

  useEffect(() => {
    if (!dialogOpen) return;

    const previousFocus =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;

    const focusTimer = window.setTimeout(() => {
      dialogRef.current
        ?.querySelector<HTMLElement>('button:not([disabled])')
        ?.focus();
    }, 0);

    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !withdrawing) {
        event.preventDefault();
        setDialogOpen(false);
        setStatusMessage('');
      }
    };

    document.addEventListener('keydown', handleKey);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener('keydown', handleKey);
      previousFocus?.focus();
    };
  }, [dialogOpen, withdrawing]);

  function openDialog() {
    setStatusMessage('');
    setDialogOpen(true);
  }

  function closeDialog() {
    if (withdrawing) return;
    setDialogOpen(false);
    setStatusMessage('');
  }

  async function confirmWithdraw() {
    if (withdrawing) return;
    setWithdrawing(true);
    setStatusMessage('');
    try {
      await withdraw();
      notifyAuthSessionEnded();
      setLoggedIn(false);
      setDialogOpen(false);
      setStatusMessage('회원 탈퇴가 완료되었습니다.');
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        notifyAuthSessionEnded();
        setLoggedIn(false);
        setDialogOpen(false);
        setStatusMessage('로그인 정보가 만료되었습니다. 다시 로그인해 주세요.');
        return;
      }
      if (error instanceof ApiError && error.status === 409) {
        setStatusMessage(
          '관리자 계정은 탈퇴할 수 없습니다. 관리자 권한을 해제한 뒤 다시 시도해 주세요.',
        );
        return;
      }
      setStatusMessage('회원 탈퇴를 완료하지 못했습니다. 다시 시도해 주세요.');
    } finally {
      setWithdrawing(false);
    }
  }

  if (checking || (!loggedIn && !statusMessage)) return null;

  return (
    <div className="account-withdrawal">
      {loggedIn ? (
        <button
          type="button"
          className="account-withdrawal__trigger"
          onClick={openDialog}
        >
          회원 탈퇴
        </button>
      ) : null}

      {statusMessage && !dialogOpen ? (
        <p className="account-withdrawal__status" role="status" aria-live="polite">
          {statusMessage}
        </p>
      ) : null}

      {dialogOpen && loggedIn ? (
        <div className="account-withdrawal__layer">
          <button
            type="button"
            className="account-withdrawal__backdrop"
            aria-label="회원 탈퇴 닫기"
            disabled={withdrawing}
            onClick={closeDialog}
          />
          <div
            ref={dialogRef}
            className="account-withdrawal__dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
          >
            <h3 id={titleId} className="account-withdrawal__title">
              회원 탈퇴
            </h3>
            <ul className="account-withdrawal__info">
              {WITHDRAW_INFO.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
            <p className="account-withdrawal__warning" role="note">
              {WITHDRAW_WARNING}
            </p>
            {statusMessage ? (
              <p className="account-withdrawal__error" role="alert">
                {statusMessage}
              </p>
            ) : null}
            <div className="account-withdrawal__actions">
              <button
                type="button"
                className="btn btn--ghost account-withdrawal__cancel"
                disabled={withdrawing}
                onClick={closeDialog}
              >
                취소
              </button>
              <button
                type="button"
                className="btn account-withdrawal__confirm"
                disabled={withdrawing}
                onClick={() => void confirmWithdraw()}
              >
                {withdrawing ? '탈퇴 처리 중…' : '탈퇴하기'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
