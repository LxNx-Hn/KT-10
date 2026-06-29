import { useEffect } from 'react';
import { useAppStore } from '@/store/appStore';
import { DISTRICT } from '@/config/district';
import MapView from '@/components/MapView';
import SearchBar from '@/components/SearchBar';
import ProfileSelector from '@/components/ProfileSelector';
import WeatherPanel from '@/components/WeatherPanel';
import RouteList from '@/components/RouteList';
import BusArrivalCard from '@/components/BusArrivalCard';
import VoiceButton from '@/components/VoiceButton';

export default function App() {
  const largeUi = useAppStore((s) => s.largeUi);
  const toggleLargeUi = useAppStore((s) => s.toggleLargeUi);
  const profile = useAppStore((s) => s.profile);

  // 데모: 부산진구청 → 서면역 기본 경로를 채우고 즉시 탐색
  useEffect(() => {
    const store = useAppStore.getState();
    store.loadDemoOd();
    void store.search();
  }, []);

  return (
    <div className={`app ${largeUi ? 'app--large' : ''}`} data-profile={profile}>
      <header className="app__header">
        <div>
          <h1 className="app__title">같이가요</h1>
          <p className="app__subtitle">{DISTRICT.name} · 접근성 경로 추천 (데모)</p>
        </div>
        <button
          type="button"
          className="btn btn--ghost app__largebtn"
          aria-pressed={largeUi}
          onClick={toggleLargeUi}
        >
          {largeUi ? '큰 글씨 ON' : '큰 글씨 OFF'}
        </button>
      </header>

      <main className="app__main">
        <MapView />
        <SearchBar />
        <ProfileSelector />
        <WeatherPanel />
        <RouteList />
        <BusArrivalCard />
      </main>

      <VoiceButton />
    </div>
  );
}
