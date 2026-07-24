import { useEffect, useRef, useState } from 'react';
import { useAppStore } from '@/store/appStore';
import { adapters } from '@/adapters';
import type { Place } from '@/types';
import { toUserMessage } from '@/api/http';

/** 장소 검색 입력 + 자동완성 드롭다운 */
function PlaceInput({
  label,
  value,
  onSelect,
}: {
  label: string;
  value: Place | null;
  onSelect: (p: Place | null) => void;
}) {
  const [text, setText] = useState(value?.name ?? '');
  const [results, setResults] = useState<Place[]>([]);
  const [open, setOpen] = useState(false);
  const [searchError, setSearchError] = useState('');
  const [searching, setSearching] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const timer = useRef<number | undefined>(undefined);
  const requestId = useRef(0);
  const inputId = `${label}-place-input`;
  const listId = `${label}-place-results`;

  useEffect(() => {
    setText(value?.name ?? '');
  }, [value]);

  useEffect(() => () => {
    requestId.current += 1;
    window.clearTimeout(timer.current);
  }, []);

  const onChange = (q: string) => {
    setText(q);
    setSearchError('');
    setResults([]);
    setOpen(false);
    setSearching(false);
    setActiveIndex(-1);
    window.clearTimeout(timer.current);
    const currentRequest = ++requestId.current;
    if (value && q !== value.name) onSelect(null);
    if (q.trim().length < 2) {
      setResults([]);
      setOpen(false);
      setSearching(false);
      return;
    }
    timer.current = window.setTimeout(async () => {
      setSearching(true);
      try {
        const r = await adapters.places.searchPlaces(q.trim());
        if (currentRequest !== requestId.current) return;
        setResults(r);
        setOpen(r.length > 0);
        setActiveIndex(r.length ? 0 : -1);
        setSearchError(
          r.length
            ? ''
            : `‘${q.trim()}’에 대한 부산 지역 검색 결과가 없습니다. 장소명이나 주소를 확인해 주세요.`,
        );
      } catch (error) {
        if (currentRequest !== requestId.current) return;
        setResults([]);
        setOpen(false);
        setSearchError(toUserMessage(error, '장소를 검색하지 못했습니다.'));
      } finally {
        if (currentRequest === requestId.current) setSearching(false);
      }
    }, 200);
  };

  const selectPlace = (place: Place) => {
    requestId.current += 1;
    window.clearTimeout(timer.current);
    onSelect(place);
    setText(place.name);
    setResults([]);
    setOpen(false);
    setSearching(false);
    setSearchError('');
    setActiveIndex(-1);
  };

  return (
    <div className="place-input">
      <label className="place-input__label" htmlFor={inputId}>{label}</label>
      <input
        id={inputId}
        className="place-input__field"
        type="text"
        role="combobox"
        value={text}
        placeholder="장소 이름 입력 (예: 서면역)"
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => results.length && setOpen(true)}
        onKeyDown={(event) => {
          if (!open || !results.length) {
            if (event.key === 'Escape') setOpen(false);
            return;
          }
          if (event.key === 'ArrowDown') {
            event.preventDefault();
            setActiveIndex((index) => (index + 1) % results.length);
          } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            setActiveIndex((index) => (index <= 0 ? results.length - 1 : index - 1));
          } else if (event.key === 'Enter' && activeIndex >= 0) {
            event.preventDefault();
            selectPlace(results[activeIndex]);
          } else if (event.key === 'Escape') {
            setOpen(false);
          }
        }}
        aria-label={label}
        aria-describedby={(searching || searchError) ? `${label}-search-status` : undefined}
        aria-autocomplete="list"
        aria-controls={listId}
        aria-expanded={open}
        aria-activedescendant={
          open && activeIndex >= 0 ? `${listId}-option-${activeIndex}` : undefined
        }
        autoComplete="off"
      />
      {(searching || searchError) && (
        <span
          className={`place-input__status${searching ? ' place-input__status--loading' : ''}`}
          id={`${label}-search-status`}
          role="status"
        >
          {searching ? '장소 검색 중…' : searchError}
        </span>
      )}
      {open && (
        <ul className="place-input__list" id={listId} role="listbox">
          {results.map((p, index) => (
            <li key={p.id} role="none">
              <button
                id={`${listId}-option-${index}`}
                type="button"
                role="option"
                tabIndex={-1}
                aria-selected={activeIndex === index}
                className={`place-input__option${
                  activeIndex === index ? ' place-input__option--active' : ''
                }`}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => selectPlace(p)}
              >
                <strong>{p.name}</strong>
                <span>{p.category ?? ''} · {p.address ?? ''}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function SearchBar() {
  const { origin, destination, setOrigin, setDestination, search, loadDemoOd, loading } =
    useAppStore();
  const useCurrentLocation = useAppStore((s) => s.useCurrentLocation);
  const isDemo = import.meta.env.VITE_DATA_SOURCE !== 'live';

  return (
    <section className="searchbar" aria-label="출발지 도착지 검색">
      <PlaceInput label="출발지" value={origin} onSelect={setOrigin} />
      <button
        type="button"
        className="searchbar__swap"
        aria-label="출발지와 도착지 바꾸기"
        onClick={() => {
          setOrigin(destination);
          setDestination(origin);
        }}
      >
        ⇅
      </button>
      <PlaceInput label="도착지" value={destination} onSelect={setDestination} />

      <div className="searchbar__actions">
        <button type="button" className="btn btn--ghost" onClick={useCurrentLocation}>
          📍 현재 위치 사용
        </button>
        {isDemo && (
          <button type="button" className="btn btn--ghost" onClick={loadDemoOd}>
            데모 경로 채우기
          </button>
        )}
        <button
          type="button"
          className="btn btn--primary"
          onClick={() => void search()}
          disabled={loading}
        >
          {loading ? '경로 찾는 중…' : '경로 찾기'}
        </button>
      </div>
    </section>
  );
}
