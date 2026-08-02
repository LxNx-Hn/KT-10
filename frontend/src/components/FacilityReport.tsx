import { useEffect, useId, useState } from 'react';
import { resolveCurrentAuth, startKakaoLogin, type ResolvedAuth } from '@/auth/api';
import { API_BASE, toUserMessage } from '@/api/http';

type AuthView = 'loading' | ResolvedAuth['status'];

export type FacilityReportProps = {
  /** 부모가 인증 상태를 넘기면 내부 auth/me 조회를 생략한다. */
  authStatus?: AuthView;
  /** 후기·신고 탭에서 공통 로그인 CTA를 쓸 때 개별 게스트 안내를 숨긴다. */
  hideGuestPrompt?: boolean;
};

/** 시설물 위치·운영상태 오류를 검토 대기열로 전달한다. 사용자 신고만으로 데이터는 바뀌지 않는다. */
export default function FacilityReport({
  authStatus,
  hideGuestPrompt = false,
}: FacilityReportProps = {}) {
  const formId = useId();
  const [internalAuthView, setInternalAuthView] = useState<AuthView>('loading');
  const authView = authStatus ?? internalAuthView;
  const [facilityName, setFacilityName] = useState('');
  const [facilityType, setFacilityType] = useState('승강기');
  const [issueType, setIssueType] = useState('relocated');
  const [description, setDescription] = useState('');
  const [coordinates, setCoordinates] = useState<{ lat: number; lng: number } | null>(null);
  const [message, setMessage] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [locating, setLocating] = useState(false);

  useEffect(() => {
    if (authStatus !== undefined) return;
    let cancelled = false;
    void resolveCurrentAuth().then((resolved) => {
      if (!cancelled) setInternalAuthView(resolved.status);
    });
    return () => {
      cancelled = true;
    };
  }, [authStatus]);

  async function submit() {
    if (authView !== 'authenticated' || submitting) return;
    const normalizedName = facilityName.trim();
    if (normalizedName.length < 2) {
      setMessage('시설물 이름을 2자 이상 입력해 주세요.');
      return;
    }
    setSubmitting(true);
    try {
      const response = await fetch(`${API_BASE}/api/facility-reports`, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          facilityName: normalizedName,
          facilityType,
          issueType,
          reportedLat: coordinates?.lat,
          reportedLng: coordinates?.lng,
          description: description.trim() || undefined,
        }),
      });
      if (response.status === 401) {
        setMessage('신고하려면 카카오 로그인이 필요합니다.');
        return;
      }
      if (response.status === 503) {
        setMessage('현재 신고 기능을 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.');
        return;
      }
      if (response.status === 429) {
        setMessage('신고 요청이 많습니다. 잠시 후 다시 시도해 주세요.');
        return;
      }
      if (!response.ok) { setMessage('신고를 저장하지 못했습니다.'); return; }
      setMessage('신고가 검토 대기열에 등록되었습니다.');
      setFacilityName('');
      setDescription('');
      setCoordinates(null);
    } catch (error) {
      setMessage(toUserMessage(error, '신고를 저장하지 못했습니다.'));
    } finally {
      setSubmitting(false);
    }
  }

  function useCurrentLocation() {
    if (authView !== 'authenticated') return;
    if (!navigator.geolocation) { setMessage('이 브라우저에서는 현재 위치를 사용할 수 없습니다.'); return; }
    if (locating) return;
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setCoordinates({ lat: position.coords.latitude, lng: position.coords.longitude });
        setMessage('현재 위치를 신고 위치로 첨부했습니다.');
        setLocating(false);
      },
      () => {
        setMessage('현재 위치를 가져오지 못했습니다. 시설물 이름과 설명으로 신고할 수 있습니다.');
        setLocating(false);
      },
      { enableHighAccuracy: true, timeout: 10000 },
    );
  }

  return (
    <section className="facility-report" aria-label="시설물 정보 오류 신고">
      <h2 className="section-title">시설물 위치나 정보가 다른가요?</h2>
      <p>신고는 검토 후 데이터에 반영됩니다.</p>

      {authView === 'loading' && !hideGuestPrompt && (
        <p role="status" aria-live="polite">로그인 상태를 확인하는 중입니다.</p>
      )}

      {authView === 'guest' && !hideGuestPrompt && (
        <>
          <p>후기와 신고 기능을 이용하려면 카카오 로그인이 필요해요.</p>
          <div className="facility-report__actions">
            <button type="button" className="btn btn--ghost" onClick={startKakaoLogin}>
              카카오 로그인
            </button>
          </div>
        </>
      )}

      {authView === 'unavailable' && !hideGuestPrompt && (
        <p role="status" aria-live="polite">
          지금은 로그인 상태를 확인하기 어렵습니다. 잠시 후 다시 시도해 주세요.
        </p>
      )}

      {authView === 'authenticated' && (
        <>
          <label htmlFor={`${formId}-name`}>
            <span>시설물 이름</span>
            <input
              id={`${formId}-name`}
              value={facilityName}
              onChange={(event) => setFacilityName(event.target.value)}
              placeholder="예: 서면역 2번 출구 승강기"
            />
          </label>
          <label htmlFor={`${formId}-type`}>
            <span>시설물 유형</span>
            <select
              id={`${formId}-type`}
              value={facilityType}
              onChange={(event) => setFacilityType(event.target.value)}
            >
              <option>승강기</option>
              <option>스마트 버스쉘터</option>
              <option>한파·무더위 쉼터</option>
              <option>전동휠체어 충전기</option>
              <option>AED</option>
              <option>기타</option>
            </select>
          </label>
          <label htmlFor={`${formId}-issue`}>
            <span>오류 유형</span>
            <select
              id={`${formId}-issue`}
              value={issueType}
              onChange={(event) => setIssueType(event.target.value)}
            >
              <option value="relocated">위치가 달라요</option>
              <option value="missing">시설물이 없어요</option>
              <option value="closed">운영하지 않아요</option>
              <option value="inaccessible">이용할 수 없어요</option>
              <option value="information_incorrect">정보가 달라요</option>
              <option value="other">기타</option>
            </select>
          </label>
          <label htmlFor={`${formId}-description`}>
            <span>확인한 내용(선택)</span>
            <textarea
              id={`${formId}-description`}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              rows={4}
            />
          </label>
          <div className="facility-report__actions">
            <button
              type="button"
              className="btn btn--ghost"
              disabled={locating || submitting}
              onClick={useCurrentLocation}
            >
              {locating ? '현재 위치 확인 중…' : coordinates ? '신고 위치 첨부됨' : '현재 위치 첨부(선택)'}
            </button>
            <button
              type="button"
              className="btn btn--primary"
              disabled={submitting}
              onClick={() => void submit()}
            >
              {submitting ? '신고 접수 중…' : '신고 접수'}
            </button>
          </div>
          {message && <p role="status" aria-live="polite">{message}</p>}
        </>
      )}
    </section>
  );
}
