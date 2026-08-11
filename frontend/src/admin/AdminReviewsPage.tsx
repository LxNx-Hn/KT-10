import { useCallback, useEffect, useState } from 'react';
import { API_BASE } from '@/api/http';
import { resolveCurrentAuth, startKakaoLogin, type ResolvedAuth } from '@/auth/api';
import './admin-reviews.css';

type ModerationStatus = 'pending' | 'verified' | 'rejected' | 'resolved';

interface ReviewListItem {
  id: string;
  routeId: string;
  rating: number;
  wasUsable: boolean;
  issueType: string | null;
  informationAccurate: boolean | null;
  trainingConsent: boolean;
  moderationStatus: ModerationStatus;
  resolutionNote: string | null;
  reviewedAt: string | null;
  createdAt: string;
  rank: number | null;
  profile: string | null;
  modelVersion: string | null;
}

interface ReviewDetail extends ReviewListItem {
  stairsDifficulty: number | null;
  slopeDifficulty: number | null;
  transferDifficulty: number | null;
  crowdingDifficulty: number | null;
  transferInformationDifficulty: number | null;
  accessibilityFacilityDifficulty: number | null;
  actualDurationMin: number | null;
  wouldReuse: boolean | null;
  comment: string | null;
  featureSnapshot: Record<string, unknown> | null;
}

interface ReviewListResponse {
  items: ReviewListItem[];
  total: number;
  limit: number;
  offset: number;
}

const PAGE_SIZE = 25;
const STATUS_LABELS: Record<ModerationStatus, string> = {
  pending: '검토 대기',
  verified: '내용 확인',
  rejected: '근거 부족',
  resolved: '조치 완료',
};

const ISSUE_LABELS: Record<string, string> = {
  stairs: '계단',
  slope: '경사',
  elevator: '승강기',
  low_floor_bus: '저상버스',
  walking_distance: '보행 거리',
  transfer: '환승',
  crowding: '혼잡',
  transfer_information: '환승 정보',
  accessibility_facility: '접근성 시설',
  duration: '소요 시간',
  safety: '안전',
  weather: '날씨',
  other: '기타',
};

function valueLabel(value: boolean | null): string {
  if (value === null) return '응답 없음';
  return value ? '예' : '아니요';
}

function difficultyLabel(value: number | null): string {
  return value === null ? '응답 없음' : `${value} / 5`;
}

function formatDate(value: string | null): string {
  if (!value) return '없음';
  return new Intl.DateTimeFormat('ko-KR', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

async function responseError(response: Response): Promise<string> {
  try {
    const body = await response.json() as { detail?: string };
    if (body.detail) return body.detail;
  } catch {
    // JSON 오류 응답이 아니면 상태 코드로 안내한다.
  }
  return `요청 실패 (${response.status})`;
}

export default function AdminReviewsPage() {
  const [auth, setAuth] = useState<ResolvedAuth | null>(null);
  const [reviews, setReviews] = useState<ReviewListResponse | null>(null);
  const [detail, setDetail] = useState<ReviewDetail | null>(null);
  const [statusFilter, setStatusFilter] = useState<ModerationStatus | ''>('pending');
  const [issueFilter, setIssueFilter] = useState('');
  const [offset, setOffset] = useState(0);
  const [note, setNote] = useState('');
  const [nextStatus, setNextStatus] = useState<ModerationStatus>('verified');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void resolveCurrentAuth().then(setAuth);
  }, []);

  const loadReviews = useCallback(async () => {
    if (auth?.status !== 'authenticated' || !auth.user.isAdmin) return;
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(offset),
      });
      if (statusFilter) params.set('status', statusFilter);
      if (issueFilter) params.set('issueType', issueFilter);
      const response = await fetch(
        `${API_BASE}/api/admin/route-reviews?${params.toString()}`,
        { credentials: 'include' },
      );
      if (!response.ok) throw new Error(await responseError(response));
      const data = await response.json() as ReviewListResponse;
      setReviews(data);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '리뷰를 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
  }, [auth, issueFilter, offset, statusFilter]);

  useEffect(() => {
    void loadReviews();
  }, [loadReviews]);

  const loadDetail = async (reviewId: string) => {
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/api/admin/route-reviews/${reviewId}`, {
        credentials: 'include',
      });
      if (!response.ok) throw new Error(await responseError(response));
      const data = await response.json() as ReviewDetail;
      setDetail(data);
      setNextStatus(data.moderationStatus === 'pending' ? 'verified' : data.moderationStatus);
      setNote(data.resolutionNote ?? '');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '리뷰 상세를 불러오지 못했습니다.');
    }
  };

  const moderate = async () => {
    if (!detail || note.trim().length < 2) {
      setError('검토 근거 또는 조치 내용을 2자 이상 입력해 주세요.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/api/admin/route-reviews/${detail.id}`, {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: nextStatus, resolutionNote: note.trim() }),
      });
      if (!response.ok) throw new Error(await responseError(response));
      const updated = await response.json() as ReviewDetail;
      setDetail(updated);
      setNote(updated.resolutionNote ?? '');
      await loadReviews();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '검토 결과를 저장하지 못했습니다.');
    } finally {
      setSaving(false);
    }
  };

  if (auth === null) {
    return <main className="admin-reviews admin-reviews--state">관리자 권한을 확인하고 있습니다.</main>;
  }
  if (auth.status === 'unavailable') {
    return <main className="admin-reviews admin-reviews--state">로그인 상태를 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.</main>;
  }
  if (auth.status === 'guest') {
    return (
      <main className="admin-reviews admin-reviews--state">
        <h1>관리자 리뷰 검토</h1>
        <p>관리자 계정으로 로그인해야 합니다.</p>
        <button type="button" onClick={startKakaoLogin}>카카오 로그인</button>
      </main>
    );
  }
  if (!auth.user.isAdmin) {
    return (
      <main className="admin-reviews admin-reviews--state">
        <h1>접근 권한이 없습니다</h1>
        <p>관리자로 지정된 계정만 사용자 리뷰를 열람할 수 있습니다.</p>
        <a href="/">지도 홈으로 돌아가기</a>
      </main>
    );
  }

  return (
    <main className="admin-reviews">
      <header className="admin-reviews__header">
        <div>
          <p className="admin-reviews__eyebrow">ACCESSIBILITY DATA REVIEW</p>
          <h1>사용자 리뷰 검토</h1>
          <p>원문과 경로 계산 스냅샷을 비교하고, 검토 결과만 별도로 기록합니다.</p>
        </div>
        <a href="/">지도 홈</a>
      </header>

      <section className="admin-reviews__filters" aria-label="리뷰 필터">
        <label>
          검토 상태
          <select
            value={statusFilter}
            onChange={(event) => {
              setStatusFilter(event.target.value as ModerationStatus | '');
              setOffset(0);
            }}
          >
            <option value="">전체</option>
            {Object.entries(STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        <label>
          문제 유형
          <select
            value={issueFilter}
            onChange={(event) => {
              setIssueFilter(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">전체</option>
            {Object.entries(ISSUE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        <span aria-live="polite">{reviews ? `총 ${reviews.total}건` : ''}</span>
      </section>

      {error && <p className="admin-reviews__error" role="alert">{error}</p>}

      <div className="admin-reviews__workspace">
        <section className="admin-reviews__list" aria-label="리뷰 목록">
          {loading && <p>불러오는 중입니다.</p>}
          {!loading && reviews?.items.length === 0 && <p>조건에 맞는 리뷰가 없습니다.</p>}
          {reviews?.items.map((review) => (
            <button
              key={review.id}
              type="button"
              className={detail?.id === review.id ? 'admin-review-card admin-review-card--selected' : 'admin-review-card'}
              onClick={() => void loadDetail(review.id)}
            >
              <span className={`admin-review-card__status admin-review-card__status--${review.moderationStatus}`}>
                {STATUS_LABELS[review.moderationStatus]}
              </span>
              <strong>{review.issueType ? ISSUE_LABELS[review.issueType] ?? review.issueType : '문제 유형 미선택'}</strong>
              <span>평점 {review.rating} · 사용 {review.wasUsable ? '가능' : '어려움'}</span>
              <span>정보 정확성: {valueLabel(review.informationAccurate)}</span>
              <small>{formatDate(review.createdAt)}</small>
            </button>
          ))}
          <nav className="admin-reviews__pagination" aria-label="리뷰 페이지">
            <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>이전</button>
            <button type="button" disabled={!reviews || offset + PAGE_SIZE >= reviews.total} onClick={() => setOffset(offset + PAGE_SIZE)}>다음</button>
          </nav>
        </section>

        <section className="admin-reviews__detail" aria-label="리뷰 상세">
          {!detail && <p>목록에서 리뷰를 선택해 주세요.</p>}
          {detail && (
            <>
              <div className="admin-reviews__detail-heading">
                <div>
                  <span>{STATUS_LABELS[detail.moderationStatus]}</span>
                  <h2>{detail.issueType ? ISSUE_LABELS[detail.issueType] ?? detail.issueType : '문제 유형 미선택'}</h2>
                </div>
                <small>{formatDate(detail.createdAt)}</small>
              </div>
              <dl className="admin-reviews__facts">
                <div><dt>경로 ID</dt><dd>{detail.routeId}</dd></div>
                <div><dt>표시 순위</dt><dd>{detail.rank ?? '기록 없음'}</dd></div>
                <div><dt>프로필</dt><dd>{detail.profile ?? '기록 없음'}</dd></div>
                <div><dt>모델</dt><dd>{detail.modelVersion ?? '기록 없음'}</dd></div>
                <div><dt>평점</dt><dd>{detail.rating} / 5</dd></div>
                <div><dt>경로 사용 가능</dt><dd>{valueLabel(detail.wasUsable)}</dd></div>
                <div><dt>정보 정확</dt><dd>{valueLabel(detail.informationAccurate)}</dd></div>
                <div><dt>재사용 의향</dt><dd>{valueLabel(detail.wouldReuse)}</dd></div>
                <div><dt>실제 소요시간</dt><dd>{detail.actualDurationMin === null ? '응답 없음' : `${detail.actualDurationMin}분`}</dd></div>
                <div><dt>학습 동의</dt><dd>{detail.trainingConsent ? '동의' : '미동의'}</dd></div>
              </dl>
              <h3>직접 체감 난이도</h3>
              <dl className="admin-reviews__facts">
                <div><dt>계단</dt><dd>{difficultyLabel(detail.stairsDifficulty)}</dd></div>
                <div><dt>경사</dt><dd>{difficultyLabel(detail.slopeDifficulty)}</dd></div>
                <div><dt>환승</dt><dd>{difficultyLabel(detail.transferDifficulty)}</dd></div>
                <div><dt>혼잡</dt><dd>{difficultyLabel(detail.crowdingDifficulty)}</dd></div>
                <div><dt>환승 정보</dt><dd>{difficultyLabel(detail.transferInformationDifficulty)}</dd></div>
                <div><dt>접근성 시설</dt><dd>{difficultyLabel(detail.accessibilityFacilityDifficulty)}</dd></div>
              </dl>
              <h3>사용자 의견</h3>
              <p className="admin-reviews__comment">{detail.comment ?? '작성된 의견이 없습니다.'}</p>
              <details className="admin-reviews__snapshot">
                <summary>서버 경로 계산 스냅샷 원문 보기</summary>
                <pre>{detail.featureSnapshot ? JSON.stringify(detail.featureSnapshot, null, 2) : '연결된 표시 기록이 없습니다.'}</pre>
              </details>
              <div className="admin-reviews__moderation">
                <h3>검토 결과 기록</h3>
                <label>
                  상태
                  <select value={nextStatus} onChange={(event) => setNextStatus(event.target.value as ModerationStatus)}>
                    {Object.entries(STATUS_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </select>
                </label>
                <label>
                  검토 근거·조치 내용
                  <textarea value={note} maxLength={2000} onChange={(event) => setNote(event.target.value)} />
                </label>
                <button type="button" disabled={saving} onClick={() => void moderate()}>
                  {saving ? '저장 중…' : '검토 결과 저장'}
                </button>
                <small>검토 상태는 원문 리뷰와 학습 동의 값을 변경하지 않습니다.</small>
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
