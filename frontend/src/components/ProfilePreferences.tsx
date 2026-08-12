import { useEffect, useState } from 'react';
import { getCurrentUser, savePreferences, AUTH_SESSION_ENDED_EVENT, type UserPreferences } from '@/auth/api';

const EMPTY: UserPreferences = {
  profile: 'general',
  usesWheelchair: false,
  usesWalkingAid: false,
  visualSupportRequired: false,
  hearingSupportRequired: false,
  avoidStairsRequired: false,
  trainingConsent: false,
};

/** 카카오 로그인 사용자에게만 저장되는 장기 이동지원 설정. */
export default function ProfilePreferences() {
  const [loggedIn, setLoggedIn] = useState(false);
  const [value, setValue] = useState<UserPreferences>(EMPTY);
  const [message, setMessage] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void getCurrentUser().then((user) => {
      if (!user) return;
      setLoggedIn(true);
      setValue({ ...EMPTY, ...user.preference });
    }).catch(() => setLoggedIn(false));
  }, []);

  useEffect(() => {
    const onSessionEnded = () => {
      setLoggedIn(false);
      setMessage('');
    };
    window.addEventListener(AUTH_SESSION_ENDED_EVENT, onSessionEnded);
    return () => window.removeEventListener(AUTH_SESSION_ENDED_EVENT, onSessionEnded);
  }, []);

  if (!loggedIn) return <p className="profile-preferences__guest">세부 이동지원 설정과 개인화는 카카오 로그인 후 저장됩니다.</p>;

  const toggle = (key: keyof UserPreferences) =>
    setValue((current) => ({ ...current, [key]: !current[key] }));

  async function persist() {
    if (saving) return;
    const { profile: _profile, ...settingsOnly } = value;
    setSaving(true);
    try {
      setValue(await savePreferences(settingsOnly));
      setMessage('저장되었습니다.');
    } catch {
      setMessage('저장하지 못했습니다.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <details className="profile-preferences">
      <summary>내 이동지원 설정</summary>
      <div className="profile-preferences__grid">
        <PreferenceCheck label="휠체어 사용" checked={value.usesWheelchair} onChange={() => toggle('usesWheelchair')} />
        <PreferenceCheck label="보행 보조기 사용" checked={value.usesWalkingAid} onChange={() => toggle('usesWalkingAid')} />
        <PreferenceCheck label="시각 안내 지원 필요" checked={value.visualSupportRequired} onChange={() => toggle('visualSupportRequired')} />
        <PreferenceCheck label="청각 안내 지원 필요" checked={value.hearingSupportRequired} onChange={() => toggle('hearingSupportRequired')} />
        <PreferenceCheck label="계단 회피 필수" checked={value.avoidStairsRequired} onChange={() => toggle('avoidStairsRequired')} />
      </div>
      <label>
        최대 도보거리(선택, m)
        <input type="number" min="100" max="15000" value={value.maxWalkDistanceM ?? ''} onChange={(event) => setValue((current) => ({ ...current, maxWalkDistanceM: event.target.value ? Number(event.target.value) : undefined }))} />
      </label>
      <label className="profile-preferences__consent">
        <input type="checkbox" checked={value.trainingConsent} onChange={() => toggle('trainingConsent')} />
        동의한 후기만 익명화해 전역 모델 후보 학습에 사용
      </label>
      <button
        type="button"
        className="btn btn--ghost"
        disabled={saving}
        onClick={() => void persist()}
      >
        {saving ? '저장 중…' : '설정 저장'}
      </button>
      {message && <p role="status" aria-live="polite">{message}</p>}
    </details>
  );
}

function PreferenceCheck({ label, checked, onChange }: { label: string; checked: boolean; onChange: () => void }) {
  return <label><input type="checkbox" checked={checked} onChange={onChange} /> {label}</label>;
}
