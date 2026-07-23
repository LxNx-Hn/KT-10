import { useAppStore } from '@/store/appStore';
import { PROFILE_LIST } from '@/config/profiles';
import { persistProfile } from '@/auth/api';

const ICON: Record<(typeof PROFILE_LIST)[number]['id'], string> = {
  general: '🧭',
  elderly: '🧓',
  child: '🧒',
  youth: '🎒',
  disabled: '♿',
  pregnant: '🤰',
};

export default function ProfileSelector() {
  const profile = useAppStore((s) => s.profile);
  const setProfile = useAppStore((s) => s.setProfile);

  return (
    <section className="profiles" aria-label="사용자 프로필 선택">
      <h2 className="section-title">사용자 프로필</h2>
      <div className="profiles__grid" role="radiogroup" aria-label="프로필">
        {PROFILE_LIST.map((p) => {
          const active = p.id === profile;
          return (
            <button
              key={p.id}
              type="button"
              role="radio"
              aria-checked={active}
              className={`profile-chip ${active ? 'profile-chip--active' : ''}`}
              onClick={() => {
                setProfile(p.id);
                void persistProfile(p.id);
              }}
            >
              <span className="profile-chip__icon" aria-hidden="true">
                {ICON[p.id]}
              </span>
              <span className="profile-chip__label">{p.label}</span>
              <span className="profile-chip__desc">{p.description}</span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
