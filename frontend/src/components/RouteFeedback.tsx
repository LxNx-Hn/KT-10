import { useEffect, useId, useState } from 'react';
import { resolveCurrentAuth, startKakaoLogin, type ResolvedAuth } from '@/auth/api';
import { useAppStore } from '@/store/appStore';
import { API_BASE } from '@/api/http';
import { serverRankedRecommendations } from '@/utils/routes';

type AuthView = 'loading' | ResolvedAuth['status'];

export type RouteFeedbackProps = {
  /** 부모가 인증 상태를 넘기면 내부 auth/me 조회를 생략한다. */
  authStatus?: AuthView;
  /** 후기·신고 탭에서 공통 로그인 CTA를 쓸 때 개별 게스트 안내를 숨긴다. */
  hideGuestPrompt?: boolean;
};

/** 로그인 사용자의 실제 이용 결과를 수집한다. 동의한 데이터만 다음 전역 학습에 쓴다. */
export default function RouteFeedback({
  authStatus,
  hideGuestPrompt = false,
}: RouteFeedbackProps = {}) {
  const selectedId = useAppStore((s) => s.selectedRouteId);
  const recommendations = useAppStore((s) => s.recommendations);
  const selected = recommendations.find((item) => item.route.id === selectedId);
  const formId = useId();
  const [internalAuthView, setInternalAuthView] = useState<AuthView>('loading');
  const authView = authStatus ?? internalAuthView;
  const [wasUsable, setWasUsable] = useState<boolean | null>(null);
  const [rating, setRating] = useState(5);
  const [trainingConsent, setTrainingConsent] = useState(false);
  const [issueType, setIssueType] = useState('');
  const [stairsDifficulty, setStairsDifficulty] = useState('');
  const [slopeDifficulty, setSlopeDifficulty] = useState('');
  const [transferDifficulty, setTransferDifficulty] = useState('');
  const [crowdingDifficulty, setCrowdingDifficulty] = useState('');
  const [transferInformationDifficulty, setTransferInformationDifficulty] = useState('');
  const [accessibilityFacilityDifficulty, setAccessibilityFacilityDifficulty] = useState('');
  const [actualDuration, setActualDuration] = useState('');
  const [wouldReuse, setWouldReuse] = useState<boolean | null>(null);
  const [informationAccurate, setInformationAccurate] = useState<boolean | null>(null);
  const [comment, setComment] = useState('');
  const [message, setMessage] = useState('');
  const [submitting, setSubmitting] = useState(false);

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

  if (!selected) return null;
  const selectedRoute = selected;

  async function submit() {
    if (authView !== 'authenticated' || submitting) return;
    if (wasUsable === null) {
      setMessage('이용 가능 여부를 선택해 주세요.');
      return;
    }
    setMessage('저장 중…');
    if (!selectedRoute.score.feedbackToken) {
      setMessage('로그인 후기용 추천 스냅샷이 없습니다. 경로를 다시 검색해 주세요.');
      return;
    }
    setSubmitting(true);
    try {
      const credentials: RequestInit = { credentials: 'include', headers: { 'Content-Type': 'application/json' } };
      const impression = await fetch(`${API_BASE}/api/route-impressions`, {
        ...credentials,
        method: 'POST',
        body: JSON.stringify({
          routeId: selectedRoute.route.id,
          rank: Math.max(
            1,
            serverRankedRecommendations(recommendations)
              .findIndex((item) => item.route.id === selectedRoute.route.id) + 1,
          ),
          feedbackToken: selectedRoute.score.feedbackToken,
        }),
      });
      if (impression.status === 401) {
        setMessage('후기를 남기려면 카카오 로그인이 필요합니다.');
        return;
      }
      if (!impression.ok) { setMessage('후기 저장 정책 또는 서버 상태를 확인해 주세요.'); return; }
      const { id } = await impression.json() as { id: string };
      const review = await fetch(`${API_BASE}/api/route-reviews`, {
        ...credentials,
        method: 'POST',
        body: JSON.stringify({
          routeId: selectedRoute.route.id,
          impressionId: id,
          wasUsable,
          rating,
          issueType: issueType || undefined,
          stairsDifficulty: stairsDifficulty ? Number(stairsDifficulty) : undefined,
          slopeDifficulty: slopeDifficulty ? Number(slopeDifficulty) : undefined,
          transferDifficulty: transferDifficulty ? Number(transferDifficulty) : undefined,
          crowdingDifficulty: crowdingDifficulty ? Number(crowdingDifficulty) : undefined,
          transferInformationDifficulty: transferInformationDifficulty
            ? Number(transferInformationDifficulty)
            : undefined,
          accessibilityFacilityDifficulty: accessibilityFacilityDifficulty
            ? Number(accessibilityFacilityDifficulty)
            : undefined,
          actualDurationMin: actualDuration ? Number(actualDuration) : undefined,
          wouldReuse: wouldReuse ?? undefined,
          informationAccurate: informationAccurate ?? undefined,
          comment: comment.trim() || undefined,
          trainingConsent,
        }),
      });
      setMessage(review.ok ? '후기가 저장되었습니다. 감사합니다.' : '후기를 저장하지 못했습니다.');
    } catch {
      setMessage('서버에 연결할 수 없어 후기를 저장하지 못했습니다.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="route-feedback" aria-label="경로 이용 후기">
      <h2 className="section-title">경로 이용 후기</h2>
      <p className="route-feedback__route">
        현재 선택: <strong>{selectedRoute.route.summary}</strong>
      </p>

      {authView === 'loading' && !hideGuestPrompt && (
        <p className="route-feedback__login-note" role="status" aria-live="polite">
          로그인 상태를 확인하는 중입니다.
        </p>
      )}

      {authView === 'guest' && !hideGuestPrompt && (
        <>
          <p className="route-feedback__login-note">
            후기와 신고 기능을 이용하려면 카카오 로그인이 필요해요.
          </p>
          <div className="route-feedback__submit">
            <button type="button" className="btn btn--kakao" onClick={startKakaoLogin}>
              카카오 로그인
            </button>
          </div>
        </>
      )}

      {authView === 'unavailable' && !hideGuestPrompt && (
        <p className="route-feedback__login-note" role="status" aria-live="polite">
          지금은 로그인 상태를 확인하기 어렵습니다. 잠시 후 다시 시도해 주세요.
        </p>
      )}

      {authView === 'authenticated' && (
        <>
          <p className="route-feedback__login-note">
            이용한 경로에 대한 후기를 남겨 주세요.
          </p>

          <fieldset className="route-feedback__usable">
            <legend>이 경로는 실제로 이용 가능했나요?</legend>
            <div className="route-feedback__usable-options">
              <button
                type="button"
                className={`chip ${wasUsable === true ? 'chip--active' : ''}`}
                aria-pressed={wasUsable === true}
                onClick={() => setWasUsable(true)}
              >
                이용 가능했어요
              </button>
              <button
                type="button"
                className={`chip ${wasUsable === false ? 'chip--active' : ''}`}
                aria-pressed={wasUsable === false}
                onClick={() => setWasUsable(false)}
              >
                이용하기 어려웠어요
              </button>
            </div>
          </fieldset>

          <label htmlFor={`${formId}-rating`}>
            만족도
            <select
              id={`${formId}-rating`}
              value={rating}
              onChange={(event) => setRating(Number(event.target.value))}
            >
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>{n}점</option>
              ))}
            </select>
          </label>
          <label htmlFor={`${formId}-issue`}>
            가장 불편했던 요소
            <select
              id={`${formId}-issue`}
              value={issueType}
              onChange={(event) => setIssueType(event.target.value)}
            >
              <option value="">항목 선택</option>
              <option value="stairs">계단</option>
              <option value="slope">경사</option>
              <option value="elevator">승강기</option>
              <option value="low_floor_bus">저상버스</option>
              <option value="walking_distance">도보거리</option>
              <option value="transfer">환승</option>
              <option value="crowding">혼잡</option>
              <option value="transfer_information">환승 안내·정보</option>
              <option value="accessibility_facility">교통약자 시설</option>
              <option value="duration">이동시간</option>
              <option value="safety">안전</option>
              <option value="weather">날씨</option>
              <option value="other">기타</option>
            </select>
          </label>
          <div className="route-feedback__details">
            <DifficultySelect
              id={`${formId}-stairs`}
              label="계단 불편"
              value={stairsDifficulty}
              onChange={setStairsDifficulty}
            />
            <DifficultySelect
              id={`${formId}-slope`}
              label="경사 불편"
              value={slopeDifficulty}
              onChange={setSlopeDifficulty}
            />
            <DifficultySelect
              id={`${formId}-transfer`}
              label="환승 불편"
              value={transferDifficulty}
              onChange={setTransferDifficulty}
            />
            <DifficultySelect
              id={`${formId}-crowding`}
              label="혼잡으로 인한 이용 불편"
              value={crowdingDifficulty}
              onChange={setCrowdingDifficulty}
            />
            <DifficultySelect
              id={`${formId}-transfer-info`}
              label="환승 안내·정보 이용 불편"
              value={transferInformationDifficulty}
              onChange={setTransferInformationDifficulty}
            />
            <DifficultySelect
              id={`${formId}-a11y`}
              label="교통약자 시설 이용 불편"
              value={accessibilityFacilityDifficulty}
              onChange={setAccessibilityFacilityDifficulty}
            />
          </div>
          <label htmlFor={`${formId}-duration`}>
            실제 이동시간(분)
            <input
              id={`${formId}-duration`}
              type="number"
              min="1"
              max="1440"
              value={actualDuration}
              onChange={(event) => setActualDuration(event.target.value)}
            />
          </label>
          <fieldset>
            <legend>다시 이용하시겠어요?</legend>
            <div className="route-feedback__chip-row">
              <button
                type="button"
                className={`chip ${wouldReuse === true ? 'chip--active' : ''}`}
                aria-pressed={wouldReuse === true}
                onClick={() => setWouldReuse(true)}
              >
                예
              </button>
              <button
                type="button"
                className={`chip ${wouldReuse === false ? 'chip--active' : ''}`}
                aria-pressed={wouldReuse === false}
                onClick={() => setWouldReuse(false)}
              >
                아니요
              </button>
            </div>
          </fieldset>
          <fieldset>
            <legend>시설물·경로 정보가 실제와 같았나요?</legend>
            <div className="route-feedback__chip-row">
              <button
                type="button"
                className={`chip ${informationAccurate === true ? 'chip--active' : ''}`}
                aria-pressed={informationAccurate === true}
                onClick={() => setInformationAccurate(true)}
              >
                같았어요
              </button>
              <button
                type="button"
                className={`chip ${informationAccurate === false ? 'chip--active' : ''}`}
                aria-pressed={informationAccurate === false}
                onClick={() => setInformationAccurate(false)}
              >
                달랐어요
              </button>
            </div>
          </fieldset>
          <label htmlFor={`${formId}-comment`}>
            추가 의견
            <textarea
              id={`${formId}-comment`}
              value={comment}
              maxLength={2000}
              rows={4}
              onChange={(event) => setComment(event.target.value)}
            />
          </label>
          <label className="route-feedback__consent" htmlFor={`${formId}-consent`}>
            <input
              id={`${formId}-consent`}
              type="checkbox"
              checked={trainingConsent}
              onChange={(event) => setTrainingConsent(event.target.checked)}
            />
            {' '}
            익명화한 후기를 다음 추천 모델 학습에 사용해도 됩니다.
          </label>

          <div className="route-feedback__submit">
            <button
              type="button"
              className="btn btn--primary"
              disabled={submitting}
              onClick={() => void submit()}
            >
              {submitting ? '후기 등록 중…' : '후기 등록'}
            </button>
          </div>
          {message && (
            <p className="route-feedback__message" role="status" aria-live="polite">
              {message}
            </p>
          )}
        </>
      )}
    </section>
  );
}

function DifficultySelect({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const options = [
    '원활함',
    '조금 어려움',
    '보통',
    '어려움',
    '매우 어려움',
  ];
  return (
    <label htmlFor={id}>
      {label}
      <select id={id} value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">선택 (기본)</option>
        {options.map((description, index) => (
          <option key={description} value={index + 1}>
            {index + 1}점 · {description}
          </option>
        ))}
      </select>
    </label>
  );
}
