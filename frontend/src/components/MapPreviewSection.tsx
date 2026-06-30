import { useEffect, useState } from 'react';
import { useAppStore } from '@/store/appStore';
import MapView from './MapView';

/**
 * 지도 보조 섹션(요구사항 §2·§11).
 * 검색 전에는 접힘(미리보기), 경로 검색 후 자동 확장. 경로 카드보다 항상 아래에 위치.
 */
export default function MapPreviewSection() {
  const hasResults = useAppStore((s) => s.recommendations.length > 0);
  const [expanded, setExpanded] = useState(false);

  // 결과가 생기면 자동 확장, 없어지면 접힘
  useEffect(() => {
    setExpanded(hasResults);
  }, [hasResults]);

  return (
    <section className="mappreview" aria-label="지도 미리보기">
      <button
        type="button"
        className="mappreview__toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded((v) => !v)}
      >
        🗺️ 지도에서 {hasResults ? '경로 확인' : '위치 미리보기'} {expanded ? '▾' : '▴'}
      </button>
      {expanded ? (
        <MapView />
      ) : (
        <p className="mappreview__hint">
          {hasResults
            ? '지도를 접었습니다. 위 버튼으로 다시 펼칠 수 있어요.'
            : '목적지를 검색하면 지도에서 경로·정류장·승강기 위치를 확인할 수 있어요.'}
        </p>
      )}
    </section>
  );
}
