/** 검색 전·빈 결과용 하단 안내. 상단 한 줄 검색 문구와 겹치지 않게 유지한다. */
export default function CollapsedGuide() {
  return (
    <div className="map-first__empty-state map-first__collapsed-guide">
      <strong>검색 전에는 경로 수치나 편의 특성을 표시하지 않습니다.</strong>
      <p>검색 결과가 생기면 이 자리에서 경로를 비교합니다.</p>
    </div>
  );
}
