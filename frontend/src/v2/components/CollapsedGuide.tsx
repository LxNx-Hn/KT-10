/** 검색 전·빈 결과용 최소 안내. 문구와 동작은 기존 empty-state와 동일하다. */
export default function CollapsedGuide() {
  return (
    <div className="map-first__empty-state map-first__collapsed-guide">
      <strong>검색 전에는 경로 수치나 편의 특성을 표시하지 않습니다.</strong>
      <p>출발지와 도착지를 선택하면 비교 가능한 경로만 보여드려요.</p>
    </div>
  );
}
