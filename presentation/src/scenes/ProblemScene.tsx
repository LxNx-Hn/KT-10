import { AnimatePresence, motion } from 'framer-motion';
import { presentationData } from '../data/presentationData';

interface ProblemSceneProps {
  step: number;
}

const routes = {
  general:
    'M 430 455 C 560 275, 720 255, 850 340 S 1040 385, 1180 455',
  elderly:
    'M 430 455 C 560 470, 690 395, 835 410 S 1030 445, 1180 455',
  mobility:
    'M 430 455 C 545 635, 710 645, 845 555 S 1040 505, 1180 455',
};

const profileOrder = [
  'general',
  'elderly',
  'mobility',
] as const;

export function ProblemScene({ step }: ProblemSceneProps) {
  const profiles = presentationData.profiles;

  return (
    <main className="problem-scene">
      <div className="problem-glow problem-glow-a" />
      <div className="problem-glow problem-glow-b" />

      <div className="presentation-hud">
        <span>02</span>
        <span className="hud-line" />
        <span>SAME DESTINATION</span>
      </div>

      <AnimatePresence mode="wait">
        {step === 0 && (
          <motion.section
            key="problem-intro"
            className="problem-intro"
            initial={{ opacity: 0, y: 28 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -18 }}
            transition={{ duration: 0.75 }}
          >
            <p className="copy-kicker">SAME A → B</p>

            <h2>
              같은 출발지.
              <br />
              같은 목적지.
            </h2>

            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.45 }}
            >
              하지만 이동하는 사람은 다릅니다.
            </motion.p>
          </motion.section>
        )}
      </AnimatePresence>

      <motion.div
        className="problem-route-stage"
        initial={{ opacity: 0 }}
        animate={{ opacity: step >= 1 ? 1 : 0 }}
        transition={{ duration: 0.7 }}
      >
        <div className="route-endpoint problem-start">
          <span className="endpoint-dot start-dot" />
          <div>
            <small>START</small>
            <strong>{presentationData.demo.origin}</strong>
          </div>
        </div>

        <div className="route-endpoint problem-end">
          <span className="endpoint-dot end-dot" />
          <div>
            <small>DESTINATION</small>
            <strong>{presentationData.demo.destination}</strong>
          </div>
        </div>

        <svg
          className="persona-routes"
          viewBox="0 0 1400 820"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <motion.path
            d={routes.general}
            className="persona-route persona-route-general"
            initial={{ pathLength: 0, opacity: 0 }}
            animate={{
              pathLength: step >= 1 ? 1 : 0,
              opacity: step >= 1 ? 1 : 0,
            }}
            transition={{ duration: 1.05 }}
          />

          <motion.path
            d={routes.elderly}
            className="persona-route persona-route-elderly"
            initial={{ pathLength: 0, opacity: 0 }}
            animate={{
              pathLength: step >= 1 ? 1 : 0,
              opacity: step >= 1 ? 1 : 0,
            }}
            transition={{ duration: 1.05 }}
          />

          <motion.path
            d={routes.mobility}
            className="persona-route persona-route-mobility"
            initial={{ pathLength: 0, opacity: 0 }}
            animate={{
              pathLength: step >= 1 ? 1 : 0,
              opacity: step >= 1 ? 1 : 0,
            }}
            transition={{ duration: 1.05 }}
          />
        </svg>

        <div className="profile-stack">
          {profileOrder.map((key, index) => {
            const profile = profiles[key];
            const visible = step >= 1;
            const isLatest = false;
            const isFinal = step >= 2;

            return (
              <motion.article
                key={key}
                className={`profile-story-card profile-${key} ${
                  isLatest ? 'is-active' : ''
                } ${isFinal ? 'is-final' : ''}`}
                initial={{ opacity: 0, x: -24 }}
                animate={{
                  opacity: visible ? 1 : 0,
                  x: visible ? 0 : -24,
                }}
                transition={{
                  duration: 0.6,
                  delay: visible ? 0.15 : 0,
                }}
              >
                <div className="profile-index">
                  0{index + 1}
                </div>

                <div className="profile-story-main">
                  <p>{profile.english}</p>
                  <h3>{profile.label}</h3>
                  <span>{profile.description}</span>
                </div>

                <div className="criteria-list">
                  {profile.criteria.map((criterion) => (
                    <span key={criterion}>{criterion}</span>
                  ))}
                </div>
              </motion.article>
            );
          })}
        </div>
      </motion.div>

      <AnimatePresence>
        {step >= 2 && (
          <motion.section
            className="problem-conclusion"
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              duration: 0.8,
              ease: [0.22, 1, 0.36, 1],
            }}
          >
            <p className="copy-kicker">ONE DESTINATION, DIFFERENT NEEDS</p>

            <h2>
              좋은 길의 기준은
              <br />
              <em>사람마다 다릅니다.</em>
            </h2>
          </motion.section>
        )}
      </AnimatePresence>

      <div className="presentation-help">
        <span>SPACE</span>
        <span>진행</span>
        <span className="help-divider">·</span>
        <span>←</span>
        <span>이전</span>
        <span className="help-divider">·</span>
        <span>R</span>
        <span>장면 처음</span>
      </div>
    </main>
  );
}
