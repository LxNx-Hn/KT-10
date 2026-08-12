import SearchBar from './SearchBar';
import VoiceChatEntryButton from './VoiceChatEntryButton';
import ProfileSelector from './ProfileSelector';
import SuggestedVoiceCommands from './SuggestedVoiceCommands';
import DemoDestinationList from './DemoDestinationList';
import RouteConditions from './RouteConditions';

/**
 * 검색 중심 홈 화면(요구사항 §2·§3·§10).
 * 지도가 아니라 "큰 검색창 + 음성 + 프로필"이 첫 화면의 중심이다.
 */
export default function SearchHome() {
  return (
    <section className="home" aria-label="검색 홈">
      <div className="home__intro">
        <p className="home__kicker">오늘의 이동을 더 편안하게</p>
        <h2 className="home__headline">어디로 가시나요?</h2>
        <p className="home__description">
          빠른 길, 완만한 길, 그늘 많은 길을 같은 기준으로 비교해 드립니다.
        </p>
      </div>
      <SearchBar />
      <VoiceChatEntryButton />
      <RouteConditions />
      <ProfileSelector />
      <SuggestedVoiceCommands />
      <DemoDestinationList />
    </section>
  );
}
