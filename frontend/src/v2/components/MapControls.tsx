function LocationIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v3M12 19v3M2 12h3M19 12h3" strokeLinecap="round" />
      <circle cx="12" cy="12" r="8" />
    </svg>
  );
}

function FacilityIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M12 2l9 5-9 5-9-5 9-5z" strokeLinejoin="round" />
      <path d="M3 12l9 5 9-5M3 17l9 5 9-5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export type MapControlsProps = {
  locating: boolean;
  showLabeledControls: boolean;
  showFacilities: boolean;
  hasFacilityOverlay: boolean;
  hasFacilityInfo: boolean;
  facilityHint: string | null;
  onLocate: () => void;
  onFacilityLayerClick: () => void;
};

export default function MapControls({
  locating,
  showLabeledControls,
  showFacilities,
  hasFacilityOverlay,
  hasFacilityInfo,
  facilityHint,
  onLocate,
  onFacilityLayerClick,
}: MapControlsProps) {
  return (
    <div className="map-first__map-controls map-first__fab-stack">
      <button
        type="button"
        className={`map-first__fab${locating ? ' map-first__fab--busy' : ''}${
          showLabeledControls ? ' map-first__fab--labeled' : ''
        }`}
        aria-label="현재 위치를 출발지로 사용"
        aria-busy={locating}
        disabled={locating}
        onClick={onLocate}
      >
        {locating ? (
          <span className="map-first__fab-spinner" aria-hidden="true" />
        ) : (
          <LocationIcon />
        )}
        {showLabeledControls && <span className="map-first__fab-label">내 위치</span>}
      </button>
      <button
        type="button"
        className={`map-first__fab${
          showFacilities && hasFacilityOverlay ? ' map-first__fab--active' : ''
        }${
          showLabeledControls ? ' map-first__fab--labeled' : ''
        }`}
        aria-label={
          hasFacilityOverlay
            ? '편의시설 오버레이'
            : hasFacilityInfo
              ? '편의시설 오버레이, 위치 데이터 없음'
              : '편의시설 오버레이 자료 없음'
        }
        aria-pressed={hasFacilityOverlay ? showFacilities : undefined}
        onClick={onFacilityLayerClick}
      >
        <FacilityIcon />
        {showLabeledControls && <span className="map-first__fab-label">편의시설</span>}
      </button>
      {facilityHint && (
        <p className="map-first__fab-hint" role="status" aria-live="polite">
          {facilityHint}
        </p>
      )}
    </div>
  );
}
