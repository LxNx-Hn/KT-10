import type { ProfileId, ScoredRoute } from '@/types';
import InstallPrompt from '@/components/InstallPrompt';
import CollapsedGuide from './CollapsedGuide';
import RouteResultList from './RouteResultList';

function ClockIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8v5l3 2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export type RouteResultsSheetProps = {
  sheetExpanded: boolean;
  loading: boolean;
  ranked: ScoredRoute[];
  profile: ProfileId;
  selectedRouteId: string | null;
  refiningRouteKeys: string[];
  sheetTitle: string;
  sheetMeta: string;
  departureButtonLabel: string;
  departureDrawerOpen: boolean;
  onToggleSheet: () => void;
  onOpenDeparture: () => void;
  onSelectRoute: (routeId: string) => void;
  onDetails: () => void;
};

export default function RouteResultsSheet({
  sheetExpanded,
  loading,
  ranked,
  profile,
  selectedRouteId,
  refiningRouteKeys,
  sheetTitle,
  sheetMeta,
  departureButtonLabel,
  departureDrawerOpen,
  onToggleSheet,
  onOpenDeparture,
  onSelectRoute,
  onDetails,
}: RouteResultsSheetProps) {
  return (
    <section
      className={`map-first__results-sheet map-first__sheet map-first__sheet--${
        sheetExpanded ? 'expanded' : 'collapsed'
      }${ranked.length === 0 ? ' map-first__sheet--empty' : ''}`}
      aria-label="경로 결과"
    >
      <div className="map-first__sheet-stack">
        <InstallPrompt />
        <button
          type="button"
          className="map-first__sheet-toggle"
          aria-expanded={sheetExpanded}
          aria-label={sheetExpanded ? '경로 결과 접기' : '경로 결과 펼치기'}
          onClick={onToggleSheet}
        >
          <span className="map-first__sheet-handle" aria-hidden="true">
            <span className="map-first__sheet-handle-bar" />
          </span>
          <span className="map-first__sheet-header">
            <span className="map-first__sheet-title">{sheetTitle}</span>
            <span className="map-first__sheet-meta">{sheetMeta}</span>
          </span>
        </button>

        {sheetExpanded && (
          <div className="map-first__sheet-body">
            {loading && (
              <p className="map-first__empty-state" role="status">
                경로를 찾고 있어요…
              </p>
            )}
            {!loading && ranked.length > 0 && (
              <>
                <button
                  type="button"
                  className="map-first__departure-btn"
                  aria-haspopup="dialog"
                  aria-expanded={departureDrawerOpen}
                  disabled={loading}
                  onClick={onOpenDeparture}
                >
                  <span className="map-first__departure-btn-icon" aria-hidden="true">
                    <ClockIcon />
                  </span>
                  <span className="map-first__departure-btn-label">
                    {departureButtonLabel}
                  </span>
                  <span className="map-first__departure-btn-chevron" aria-hidden="true">
                    ▾
                  </span>
                </button>
                <RouteResultList
                  recommendations={ranked}
                  profile={profile}
                  selectedRouteId={selectedRouteId}
                  refiningRouteKeys={refiningRouteKeys}
                  onSelectRoute={onSelectRoute}
                  onDetails={onDetails}
                />
              </>
            )}
            {!loading && ranked.length === 0 && <CollapsedGuide />}
          </div>
        )}
      </div>
    </section>
  );
}
