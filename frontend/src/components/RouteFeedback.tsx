import { useState } from 'react';
import { useAppStore } from '@/store/appStore';

const BASE = (import.meta.env.VITE_API_BASE ?? 'http://localhost:8000').replace(/\/$/, '');

/** 로그인 사용자의 실제 이용 결과를 수집한다. 동의한 데이터만 다음 전역 학습에 쓴다. */
export default function RouteFeedback() {
  const selectedId = useAppStore((s) => s.selectedRouteId);
  const selected = useAppStore((s) => s.recommendations.find((item) => item.route.id === selectedId));
  const [rating, setRating] = useState(5);
  const [trainingConsent, setTrainingConsent] = useState(false);
  const [message, setMessage] = useState('');

  if (!selected) return null;
  const selectedRoute = selected;

  async function submit(wasUsable: boolean) {
    setMessage('저장 중…');
    const credentials: RequestInit = { credentials: 'include', headers: { 'Content-Type': 'application/json' } };
    const snapshot = JSON.stringify({ route: selectedRoute.route, components: selectedRoute.score.components });
    const impression = await fetch(`${BASE}/api/route-impressions`, {
      ...credentials, method: 'POST', body: JSON.stringify({ routeId: selectedRoute.route.id, rank: 1, featureSnapshot: snapshot }),
    });
    if (impression.status === 401 || impression.status === 503) {
      setMessage('후기를 남기려면 카카오 로그인이 필요합니다.');
      return;
    }
    if (!impression.ok) { setMessage('후기를 저장하지 못했습니다.'); return; }
    const { id } = await impression.json() as { id: string };
    const review = await fetch(`${BASE}/api/route-reviews`, {
      ...credentials,
      method: 'POST',
      body: JSON.stringify({ routeId: selectedRoute.route.id, impressionId: id, wasUsable, rating, trainingConsent }),
    });
    setMessage(review.ok ? '후기가 저장되었습니다. 감사합니다.' : '후기를 저장하지 못했습니다.');
  }

  return (
    <section className="route-feedback" aria-label="경로 이용 후기">
      <h2 className="section-title">이 경로는 실제로 이용 가능했나요?</h2>
      <div className="route-feedback__actions">
        <button type="button" className="btn btn--ghost" onClick={() => void submit(true)}>이용 가능했어요</button>
        <button type="button" className="btn btn--ghost" onClick={() => void submit(false)}>이용하기 어려웠어요</button>
      </div>
      <label>만족도 <select value={rating} onChange={(event) => setRating(Number(event.target.value))}>{[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}점</option>)}</select></label>
      <label className="route-feedback__consent"><input type="checkbox" checked={trainingConsent} onChange={(event) => setTrainingConsent(event.target.checked)} /> 익명화한 후기를 다음 추천 모델 학습에 사용해도 됩니다.</label>
      {message && <p className="route-feedback__message">{message}</p>}
    </section>
  );
}
