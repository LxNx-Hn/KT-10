import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type RefObject,
} from 'react';
import { adapters } from '@/adapters';
import { toUserMessage } from '@/api/http';
import type { Place } from '@/types';

function placeSubtitle(place: Place): string {
  return [place.category, place.address]
    .filter((part): part is string => Boolean(part?.trim()))
    .join(' · ');
}

type PlaceComboboxProps = {
  fieldId: string;
  label: string;
  place: Place | null;
  onSelectPlace: (place: Place) => void;
  onClearPlace: () => void;
  inputRef?: RefObject<HTMLInputElement>;
  onSelected?: () => void;
};

/**
 * 카카오 장소 검색 어댑터를 사용하는 접근 가능한 자동완성 입력.
 * 입력 문자열과 실제로 선택된 Place를 분리해 좌표 없는 검색을 보내지 않는다.
 */
export default function PlaceCombobox({
  fieldId,
  label,
  place,
  onSelectPlace,
  onClearPlace,
  inputRef,
  onSelected,
}: PlaceComboboxProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const timeoutRef = useRef<number>();
  const requestIdRef = useRef(0);
  const mountedRef = useRef(true);
  const locallyClearingSelectionRef = useRef(false);
  const [text, setText] = useState(place?.name ?? '');
  const [results, setResults] = useState<Place[]>([]);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [searching, setSearching] = useState(false);
  const [empty, setEmpty] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const listboxId = `${fieldId}-listbox`;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestIdRef.current += 1;
      window.clearTimeout(timeoutRef.current);
    };
  }, []);

  useEffect(() => {
    if (locallyClearingSelectionRef.current && place === null) {
      locallyClearingSelectionRef.current = false;
      return;
    }
    requestIdRef.current += 1;
    window.clearTimeout(timeoutRef.current);
    setText(place?.name ?? '');
    setResults([]);
    setOpen(false);
    setActiveIndex(-1);
    setSearching(false);
    setEmpty(false);
    setLocalError(null);
  }, [place]);

  useEffect(() => {
    const closeFromOutside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
        setActiveIndex(-1);
      }
    };
    document.addEventListener('pointerdown', closeFromOutside);
    return () => document.removeEventListener('pointerdown', closeFromOutside);
  }, []);

  const closeList = () => {
    setOpen(false);
    setActiveIndex(-1);
  };

  const applyPlace = (next: Place) => {
    requestIdRef.current += 1;
    window.clearTimeout(timeoutRef.current);
    onSelectPlace(next);
    setText(next.name);
    setResults([]);
    setSearching(false);
    setEmpty(false);
    setLocalError(null);
    closeList();
    onSelected?.();
  };

  const searchPlaces = async (query: string, requestId: number) => {
    setSearching(true);
    setLocalError(null);
    try {
      const found = await adapters.places.searchPlaces(query);
      if (!mountedRef.current || requestId !== requestIdRef.current) return;
      setResults(found);
      setEmpty(found.length === 0);
      setActiveIndex(found.length > 0 ? 0 : -1);
      setOpen(true);
    } catch (error) {
      if (!mountedRef.current || requestId !== requestIdRef.current) return;
      setResults([]);
      setEmpty(false);
      setActiveIndex(-1);
      setLocalError(toUserMessage(error, '장소 검색에 실패했습니다.'));
      setOpen(true);
    } finally {
      if (mountedRef.current && requestId === requestIdRef.current) {
        setSearching(false);
      }
    }
  };

  const onChange = (value: string) => {
    const requestId = ++requestIdRef.current;
    window.clearTimeout(timeoutRef.current);
    setText(value);
    setSearching(false);
    setLocalError(null);
    setResults([]);
    setActiveIndex(-1);

    if (place && value !== place.name) {
      locallyClearingSelectionRef.current = true;
      onClearPlace();
    }

    const query = value.trim();
    if (query.length < 2) {
      setOpen(false);
      setEmpty(false);
      return;
    }

    setEmpty(false);
    timeoutRef.current = window.setTimeout(() => {
      void searchPlaces(query, requestId);
    }, 200);
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') {
      if (open) event.preventDefault();
      closeList();
      return;
    }
    if (!open || results.length === 0) return;

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActiveIndex((index) => (index + 1) % results.length);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveIndex((index) => (index <= 0 ? results.length - 1 : index - 1));
    } else if (event.key === 'Enter' && activeIndex >= 0) {
      event.preventDefault();
      applyPlace(results[activeIndex]);
    }
  };

  const showList =
    open && (searching || results.length > 0 || empty || localError !== null);

  return (
    <div className="map-first__combobox" ref={rootRef}>
      <div className="map-first__search-row">
        <span
          className={`map-first__search-dot map-first__search-dot--${
            fieldId.includes('origin') ? 'origin' : 'dest'
          }`}
          aria-hidden="true"
        />
        <label className="map-first__sr-only" htmlFor={fieldId}>
          {label}
        </label>
        <input
          ref={inputRef}
          id={fieldId}
          className="map-first__search-input"
          type="search"
          role="combobox"
          value={text}
          placeholder={`${label} 검색`}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={onKeyDown}
          onFocus={() => {
            if (results.length > 0 || empty || localError) setOpen(true);
          }}
          aria-label={label}
          aria-expanded={showList}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-busy={searching}
          aria-activedescendant={
            activeIndex >= 0 ? `${fieldId}-option-${activeIndex}` : undefined
          }
          autoComplete="off"
        />
      </div>

      {showList && (
        <div
          className="map-first__suggest"
          id={listboxId}
          role="listbox"
          aria-label={`${label} 검색 결과`}
        >
          {searching && (
            <p className="map-first__suggest-status" role="status">
              카카오 장소를 검색하는 중…
            </p>
          )}
          {localError && (
            <p className="map-first__suggest-status" role="alert">
              {localError}
            </p>
          )}
          {!searching && !localError && empty && (
            <p className="map-first__suggest-status" role="status">
              검색 결과가 없습니다. 다른 장소명이나 주소를 입력해 주세요.
            </p>
          )}
          {!searching &&
            results.map((item, index) => {
              const subtitle = placeSubtitle(item);
              const active = index === activeIndex;
              return (
                <button
                  key={`${item.id}-${index}`}
                  id={`${fieldId}-option-${index}`}
                  type="button"
                  role="option"
                  aria-selected={active}
                  className={`map-first__suggest-option${
                    active ? ' map-first__suggest-option--active' : ''
                  }`}
                  onPointerDown={(event) => event.preventDefault()}
                  onPointerEnter={() => setActiveIndex(index)}
                  onClick={() => applyPlace(item)}
                >
                  <span className="map-first__suggest-name">{item.name}</span>
                  {subtitle && (
                    <span className="map-first__suggest-sub">{subtitle}</span>
                  )}
                </button>
              );
            })}
        </div>
      )}
    </div>
  );
}
