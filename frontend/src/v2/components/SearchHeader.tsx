import type { RefObject } from 'react';
import type { Place } from '@/types';
import type { ToggleableScoringOption } from '@/store/appStore';
import RouteSearchPanel, { type SearchPanelMode } from './RouteSearchPanel';

type QuickCondition = {
  key: ToggleableScoringOption;
  label: string;
};

export type SearchHeaderProps = {
  mode: SearchPanelMode;
  origin: Place | null;
  destination: Place | null;
  originInputRef?: RefObject<HTMLInputElement>;
  destinationInputRef?: RefObject<HTMLInputElement>;
  loading: boolean;
  searchHint: string | null;
  error: string | null;
  profileLabel: string;
  profileDrawerOpen: boolean;
  settingsDrawerOpen: boolean;
  situationConditions: QuickCondition[];
  routeOptionConditions: QuickCondition[];
  optionState: Partial<Record<ToggleableScoringOption, boolean | undefined>>;
  largeUi: boolean;
  activeConditionCount: number;
  summaryConditionCount: number;
  conditionsDrawerOpen: boolean;
  onSelectOrigin: (place: Place) => void;
  onClearOrigin: () => void;
  onSelectDestination: (place: Place) => void;
  onClearDestination: () => void;
  onSwap: () => void;
  onSearch: () => void;
  onEditSearch: () => void;
  onOpenProfile: () => void;
  onOpenSettings: () => void;
  onToggleOption: (key: ToggleableScoringOption, enabled: boolean) => void;
  onToggleLargeUi: () => void;
  onOpenConditions: () => void;
};

/**
 * 검색 화면 골격. expanded/compact 프레젠테이션은 RouteSearchPanel에 위임하고
 * 이후 한 줄 검색으로 접을 수 있도록 루트 경계를 둔다.
 */
export default function SearchHeader(props: SearchHeaderProps) {
  return (
    <div
      className="map-first__search-header"
      data-search-header={props.mode}
    >
      <div className="map-first__search-header-body">
        <RouteSearchPanel {...props} />
      </div>
    </div>
  );
}
