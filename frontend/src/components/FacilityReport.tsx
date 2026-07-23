import { useState } from 'react';
import { API_BASE, toUserMessage } from '@/api/http';

/** 시설물 위치·운영상태 오류를 검토 대기열로 전달한다. 사용자 신고만으로 데이터는 바뀌지 않는다. */
export default function FacilityReport() {
  const [facilityName, setFacilityName] = useState('');
  const [facilityType, setFacilityType] = useState('승강기');
  const [issueType, setIssueType] = useState('relocated');
  const [description, setDescription] = useState('');
  const [coordinates, setCoordinates] = useState<{ lat: number; lng: number } | null>(null);
  const [message, setMessage] = useState('');

  async function submit() {
    if (facilityName.trim().length < 2) { setMessage('시설물 이름을 2자 이상 입력해 주세요.'); return; }
    try {
      const response = await fetch(`${API_BASE}/api/facility-reports`, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ facilityName, facilityType, issueType, reportedLat: coordinates?.lat, reportedLng: coordinates?.lng, description: description || undefined }),
      });
      if (response.status === 401 || response.status === 503) { setMessage('신고하려면 카카오 로그인이 필요합니다.'); return; }
      if (!response.ok) { setMessage('신고를 저장하지 못했습니다.'); return; }
      setMessage('신고가 검토 대기열에 등록되었습니다.');
      setFacilityName(''); setDescription('');
    } catch (error) {
      setMessage(toUserMessage(error, '신고를 저장하지 못했습니다.'));
    }
  }

  function useCurrentLocation() {
    if (!navigator.geolocation) { setMessage('이 브라우저에서는 현재 위치를 사용할 수 없습니다.'); return; }
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setCoordinates({ lat: position.coords.latitude, lng: position.coords.longitude });
        setMessage('현재 위치를 신고 위치로 첨부했습니다.');
      },
      () => setMessage('현재 위치를 가져오지 못했습니다. 시설물 이름과 설명으로 신고할 수 있습니다.'),
      { enableHighAccuracy: true, timeout: 10000 },
    );
  }

  return (
    <section className="facility-report" aria-label="시설물 정보 오류 신고">
      <h2 className="section-title">시설물 위치나 정보가 다른가요?</h2>
      <p>신고는 검토 후 데이터에 반영됩니다.</p>
      <input value={facilityName} onChange={(event) => setFacilityName(event.target.value)} placeholder="예: 서면역 2번 출구 승강기" aria-label="시설물 이름" />
      <select value={facilityType} onChange={(event) => setFacilityType(event.target.value)} aria-label="시설물 유형"><option>승강기</option><option>스마트 버스쉘터</option><option>한파·무더위 쉼터</option><option>전동휠체어 충전기</option><option>AED</option><option>기타</option></select>
      <select value={issueType} onChange={(event) => setIssueType(event.target.value)} aria-label="오류 유형"><option value="relocated">위치가 달라요</option><option value="missing">시설물이 없어요</option><option value="closed">운영하지 않아요</option><option value="inaccessible">이용할 수 없어요</option><option value="information_incorrect">정보가 달라요</option><option value="other">기타</option></select>
      <textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="확인한 내용(선택)" aria-label="신고 설명" />
      <button type="button" className="btn btn--ghost" onClick={useCurrentLocation}>{coordinates ? '신고 위치 첨부됨' : '현재 위치 첨부(선택)'}</button>
      <button type="button" className="btn btn--ghost" onClick={() => void submit()}>시설물 오류 신고</button>
      {message && <p role="status">{message}</p>}
    </section>
  );
}
