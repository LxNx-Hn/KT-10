import type { ProfileId, ProfileMeta } from '@/types';

export function ProfileIcon({ profileId }: { profileId: ProfileId }) {
  const common = (
    <>
      <circle cx="12" cy="6" r="2.5" />
      <path d="M7.5 21c.4-5 1.9-8 4.5-8s4.1 3 4.5 8" />
    </>
  );

  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      data-profile-icon={profileId}
      aria-hidden="true"
    >
      {profileId === 'general' && common}
      {profileId === 'elderly' && (
        <>
          <circle cx="9" cy="5" r="2" />
          <path d="m9 8-1 5 3 2 1 5M8 13l-3 6M11 10l3 2" />
          <path d="M17 10v9.5a1.5 1.5 0 0 0 3 0" />
        </>
      )}
      {profileId === 'child' && (
        <>
          <circle cx="12" cy="6.5" r="2.25" />
          <path d="M12 9v6M7.5 12l4.5-2 4.5 2M12 15l-3 5M12 15l3 5" />
        </>
      )}
      {profileId === 'youth' && (
        <>
          <path d="m4 8 8-4 8 4-8 4-8-4Z" />
          <path d="M7.5 10.5V15c2.8 2 6.2 2 9 0v-4.5M20 8v5" />
        </>
      )}
      {profileId === 'disabled' && (
        <>
          <circle cx="10" cy="4.5" r="2" />
          <path d="m10 7.5 1 5h4l3 5M10.5 10H7" />
          <path d="M14.5 17a5.5 5.5 0 1 1-6-7" />
        </>
      )}
      {profileId === 'pregnant' && (
        <>
          <circle cx="11" cy="5" r="2.25" />
          <path d="M10.5 8v4M10.5 12c5-1 6 5 3 7M10.5 12 8 20M13.5 19H18" />
        </>
      )}
    </svg>
  );
}

function SelectedCheckIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="9" />
      <path d="m8 12 2.6 2.6L16.5 9" />
    </svg>
  );
}

export default function ProfileOptionCard({
  item,
  selected,
  mobile,
  onSelect,
}: {
  item: ProfileMeta;
  selected: boolean;
  mobile: boolean;
  onSelect: (profileId: ProfileId) => void;
}) {
  const selectedClass = selected
    ? ' map-first__profile-option--selected'
    : '';
  const keywords = item.keywords.slice(0, 2);

  if (!mobile) {
    return (
      <button
        type="button"
        role="radio"
        aria-checked={selected}
        aria-label={`${item.label}. ${item.description}`}
        className={`map-first__profile-option${selectedClass}`}
        onClick={() => onSelect(item.id)}
      >
        <strong>{item.label}</strong>
        <span>{item.description}</span>
      </button>
    );
  }

  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      aria-label={`${item.label}. ${item.description}`}
      className={`map-first__profile-option map-first__profile-option--mobile${selectedClass}`}
      data-profile-option={item.id}
      onClick={() => onSelect(item.id)}
    >
      <span className="map-first__profile-option-icon" aria-hidden="true">
        <ProfileIcon profileId={item.id} />
      </span>
      <span className="map-first__profile-option-copy">
        <strong>{item.label}</strong>
        <span className="map-first__profile-option-keywords" aria-hidden="true">
          {keywords.map((keyword) => (
            <span key={keyword} className="map-first__profile-keyword">
              {keyword}
            </span>
          ))}
        </span>
      </span>
      {selected && (
        <span className="map-first__profile-option-check" aria-hidden="true">
          <SelectedCheckIcon />
        </span>
      )}
    </button>
  );
}
