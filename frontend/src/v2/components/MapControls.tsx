import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react';

function LocationIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v3M12 19v3M2 12h3M19 12h3" strokeLinecap="round" />
      <circle cx="12" cy="12" r="8" />
    </svg>
  );
}

function LayersIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M12 2l9 5-9 5-9-5 9-5z" strokeLinejoin="round" />
      <path d="M3 12l9 5 9-5M3 17l9 5 9-5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

type LayerToggleRowProps = {
  id: string;
  label: string;
  checked: boolean;
  enabled: boolean;
  disabledHint: string;
  onToggle: () => void;
};

function LayerToggleRow({
  id,
  label,
  checked,
  enabled,
  disabledHint,
  onToggle,
}: LayerToggleRowProps) {
  return (
    <div className="map-first__map-info-row">
      <div className="map-first__map-info-row-main">
        <label className="map-first__map-info-label" htmlFor={id}>
          {label}
        </label>
        <button
          id={id}
          type="button"
          role="switch"
          className={`map-first__map-info-switch${
            checked && enabled ? ' map-first__map-info-switch--on' : ''
          }`}
          aria-checked={enabled ? checked : false}
          aria-label={label}
          disabled={!enabled}
          onClick={onToggle}
        >
          <span className="map-first__map-info-switch-thumb" aria-hidden="true" />
        </button>
      </div>
      {!enabled && (
        <p className="map-first__map-info-hint">{disabledHint}</p>
      )}
    </div>
  );
}

export type MapControlsProps = {
  locating: boolean;
  showLabeledControls: boolean;
  showFacilities: boolean;
  hasFacilityOverlay: boolean;
  facilityDisabledHint: string;
  showShade: boolean;
  hasShadeOverlay: boolean;
  shadeDisabledHint: string;
  showSlope: boolean;
  hasSlopeOverlay: boolean;
  slopeDisabledHint: string;
  onLocate: () => void;
  onToggleFacilities: () => void;
  onToggleShade: () => void;
  onToggleSlope: () => void;
};

export default function MapControls({
  locating,
  showLabeledControls,
  showFacilities,
  hasFacilityOverlay,
  facilityDisabledHint,
  showShade,
  hasShadeOverlay,
  shadeDisabledHint,
  showSlope,
  hasSlopeOverlay,
  slopeDisabledHint,
  onLocate,
  onToggleFacilities,
  onToggleShade,
  onToggleSlope,
}: MapControlsProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const panelId = useId();
  const facilityId = useId();
  const shadeId = useId();
  const slopeId = useId();

  const anyOverlayActive =
    (showFacilities && hasFacilityOverlay)
    || (showShade && hasShadeOverlay)
    || (showSlope && hasSlopeOverlay);

  useEffect(() => {
    if (!open) return;

    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setOpen(false);
      }
    };

    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  const onMenuKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'Escape' && open) {
      event.preventDefault();
      setOpen(false);
    }
  };

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

      <div className="map-first__map-info" ref={rootRef}>
        <button
          type="button"
          className={`map-first__fab${
            open || anyOverlayActive ? ' map-first__fab--active' : ''
          }${open ? ' map-first__fab--menu-open' : ''}${
            showLabeledControls ? ' map-first__fab--labeled' : ''
          }`}
          aria-label="지도 정보"
          aria-expanded={open}
          aria-controls={panelId}
          aria-haspopup="dialog"
          onClick={() => setOpen((value) => !value)}
          onKeyDown={onMenuKeyDown}
        >
          <LayersIcon />
          {showLabeledControls && (
            <span className="map-first__fab-label">지도 정보</span>
          )}
        </button>

        {open && (
          <div
            id={panelId}
            className="map-first__map-info-panel"
            role="dialog"
            aria-label="지도 정보"
          >
            <h2 className="map-first__map-info-title">지도 정보</h2>
            <div className="map-first__map-info-list">
              <LayerToggleRow
                id={facilityId}
                label="편의시설"
                checked={showFacilities}
                enabled={hasFacilityOverlay}
                disabledHint={facilityDisabledHint}
                onToggle={onToggleFacilities}
              />
              <LayerToggleRow
                id={shadeId}
                label="건물 그늘"
                checked={showShade}
                enabled={hasShadeOverlay}
                disabledHint={shadeDisabledHint}
                onToggle={onToggleShade}
              />
              <LayerToggleRow
                id={slopeId}
                label="도보 경사"
                checked={showSlope}
                enabled={hasSlopeOverlay}
                disabledHint={slopeDisabledHint}
                onToggle={onToggleSlope}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
