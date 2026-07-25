import { useState } from 'react';
import { useAppStore } from '@/store/appStore';
import { API_BASE } from '@/api/http';
import { serverRankedRecommendations } from '@/utils/routes';

/** 로그인 사용자의 실제 이용 결과를 수집한다. 동의한 데이터만 다음 전역 학습에 쓴다. */
export default function RouteFeedback() {
  const selectedId = useAppStore((s) => s.selectedRouteId);
  const recommendations = useAppStore((s) => s.recommendations);
  const selected = recommendations.find((item) => item.route.id === selectedId);
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

  if (!selected) return null;
  const selectedRoute = selected;

  async function submit(wasUsable: boolean) {
    if (submitting) return;
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
      <h2 className="section-title">이 경로는 실제로 이용 가능했나요?</h2>
      <p className="route-feedback__route">
        현재 선택: <strong>{selectedRoute.route.summary}</strong>
      </p>
      <p className="route-feedback__login-note">
        후기를 저장하려면 카카오 로그인이 필요합니다.
      </p>
      <div className="route-feedback__actions">
        <button
          type="button"
          className="btn btn--ghost"
          disabled={submitting}
          onClick={() => void submit(true)}
        >
          이용 가능했어요
        </button>
        <button
          type="button"
          className="btn btn--ghost"
          disabled={submitting}
          onClick={() => void submit(false)}
        >
          이용하기 어려웠어요
        </button>
      </div>
      <label>만족도 <select value={rating} onChange={(event) => setRating(Number(event.target.value))}>{[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}점</option>)}</select></label>
      <label>가장 불편했던 요소 <select value={issueType} onChange={(event) => setIssueType(event.target.value)}><option value="">항목 선택</option><option value="stairs">계단</option><option value="slope">경사</option><option value="elevator">승강기</option><option value="low_floor_bus">저상버스</option><option value="walking_distance">도보거리</option><option value="transfer">환승</option><option value="crowding">혼잡</option><option value="transfer_information">환승 안내·정보</option><option value="accessibility_facility">교통약자 시설</option><option value="duration">이동시간</option><option value="safety">안전</option><option value="weather">날씨</option><option value="other">기타</option></select></label>
      <div className="route-feedback__details">
        <DifficultySelect label="계단 불편" value={stairsDifficulty} onChange={setStairsDifficulty} />
        <DifficultySelect label="경사 불편" value={slopeDifficulty} onChange={setSlopeDifficulty} />
        <DifficultySelect label="환승 불편" value={transferDifficulty} onChange={setTransferDifficulty} />
        <DifficultySelect
          label="혼잡으로 인한 이용 불편"
          value={crowdingDifficulty}
          onChange={setCrowdingDifficulty}
        />
        <DifficultySelect
          label="환승 안내·정보 이용 불편"
          value={transferInformationDifficulty}
          onChange={setTransferInformationDifficulty}
        />
        <DifficultySelect
          label="교통약자 시설 이용 불편"
          value={accessibilityFacilityDifficulty}
          onChange={setAccessibilityFacilityDifficulty}
        />
      </div>
      <label>실제 이동시간(분) <input type="number" min="1" max="1440" value={actualDuration} onChange={(event) => setActualDuration(event.target.value)} /></label>
      <fieldset><legend>다시 이용하시겠어요?</legend><button type="button" className={`chip ${wouldReuse === true ? 'chip--active' : ''}`} aria-pressed={wouldReuse === true} onClick={() => setWouldReuse(true)}>예</button><button type="button" className={`chip ${wouldReuse === false ? 'chip--active' : ''}`} aria-pressed={wouldReuse === false} onClick={() => setWouldReuse(false)}>아니요</button></fieldset>
      <fieldset><legend>시설물·경로 정보가 실제와 같았나요?</legend><button type="button" className={`chip ${informationAccurate === true ? 'chip--active' : ''}`} aria-pressed={informationAccurate === true} onClick={() => setInformationAccurate(true)}>같았어요</button><button type="button" className={`chip ${informationAccurate === false ? 'chip--active' : ''}`} aria-pressed={informationAccurate === false} onClick={() => setInformationAccurate(false)}>달랐어요</button></fieldset>
      <label>추가 의견 <textarea value={comment} maxLength={2000} rows={4} onChange={(event) => setComment(event.target.value)} /></label>
      <label className="route-feedback__consent"><input type="checkbox" checked={trainingConsent} onChange={(event) => setTrainingConsent(event.target.checked)} /> 익명화한 후기를 다음 추천 모델 학습에 사용해도 됩니다.</label>
      {message && <p className="route-feedback__message" role="status" aria-live="polite">{message}</p>}
    </section>
  );
}

function DifficultySelect({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  const options = [
    '원활함',
    '조금 어려움',
    '보통',
    '어려움',
    '매우 어려움',
  ];
  return (
    <label>
      {label}{' '}
      <select value={value} onChange={(event) => onChange(event.target.value)}>
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
