import SearchBar from './SearchBar';
import VoiceChatEntryButton from './VoiceChatEntryButton';
import ProfileSelector from './ProfileSelector';
import SuggestedVoiceCommands from './SuggestedVoiceCommands';
import DemoDestinationList from './DemoDestinationList';
import RouteConditions from './RouteConditions';
import ProfilePreferences from './ProfilePreferences';

/**
 * 검색 중심 홈 화면(요구사항 §2·§3·§10).
 * 지도가 아니라 "큰 검색창 + 음성 + 프로필"이 첫 화면의 중심이다.
 */
export default function SearchHome() {
  return (
    <section className="home" aria-label="검색 홈">
      <h2 className="home__headline">어디로 가시나요?</h2>
      <SearchBar />
      <VoiceChatEntryButton />
      <RouteConditions />
      <ProfileSelector />
      <ProfilePreferences />
      <SuggestedVoiceCommands />
      <DemoDestinationList />
    </section>
  );
}
