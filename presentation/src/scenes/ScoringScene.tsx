import { AnimatePresence, motion } from 'framer-motion';

interface ScoringSceneProps {
  step: number;
}

const groups = [
  {
    title: '이동 부담',
    en: 'MOVEMENT',
    items: [
      ['TIME EFFICIENCY', '시간 효율'],
      ['WALK COMFORT', '보행 편의'],
      ['SLOPE COMFORT', '경사 편의'],
      ['TRANSFER', '환승 단순성'],
    ],
  },
  {
    title: '접근성',
    en: 'ACCESSIBILITY',
    items: [
      ['ACCESSIBILITY', '접근성'],
      ['ELEVATOR', '승강기'],
      ['LOW FLOOR BUS', '저상버스'],
    ],
  },
  {
    title: '환경 · 신뢰',
    en: 'CONTEXT',
    items: [
      ['SHADE', '그늘 편의'],
      ['WEATHER', '날씨 안전'],
      ['SAFETY', '안전'],
      ['RELIABILITY', '데이터 신뢰도'],
    ],
  },
];

const profiles = [
  '일반',
  '고령자',
  '아동',
  '청년',
  '이동지원',
  '임산부',
];

const options = [
  '짐 많음',
  '유아차',
  '저상버스 우선',
  '날씨 회피',
  '계단 회피',
  '그늘 우선',
  '환승 최소',
  '출발시각',
];

export function ScoringScene({
  step,
}: ScoringSceneProps) {
  return (
    <main className="score-scene product-light">
      <div className="score-grid-bg" />
      <div className="score-ambient score-ambient-a" />
      <div className="score-ambient score-ambient-b" />

      <div className="presentation-hud">
        <span>08</span>
        <span className="hud-line" />
        <span>FROM FEATURES TO SCORE</span>
      </div>

      <AnimatePresence mode="wait">
        {step === 0 && (
          <motion.section
            key="score-intro"
            className="score-intro"
            initial={{ opacity: 0, y: 28 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -16 }}
            transition={{ duration: 0.7 }}
          >
            <p className="copy-kicker">
              PERSONALIZED SCORING
            </p>

            <h2>
              맞춤 적합도는
              <br />
              <em>숫자 하나에서 시작되지 않습니다.</em>
            </h2>

            <p>
              하나의 경로를 여러 평가 요소로 나누고,
              <br />
              사용자 조건에 맞춰 다시 결합합니다.
            </p>
          </motion.section>
        )}
      </AnimatePresence>

      <motion.section
        className="score-components-stage"
        initial={{ opacity: 0 }}
        animate={{
          opacity:
            step === 1
              ? 1
              : step >= 2
                ? 0.08
                : 0,
        }}
        transition={{ duration: 0.6 }}
      >
        <div className="score-groups">
          {groups.map((group, groupIndex) => (
            <motion.article
              key={group.title}
              className="score-group"
              initial={{
                opacity: 0,
                y: 22,
              }}
              animate={{
                opacity: step >= 1 ? 1 : 0,
                y: step >= 1 ? 0 : 22,
              }}
              transition={{
                delay: groupIndex * 0.12,
                duration: 0.6,
              }}
            >
              <div className="score-group-title">
                <small>{group.en}</small>
                <h3>{group.title}</h3>
              </div>

              <div className="score-component-list">
                {group.items.map(([en, ko], index) => (
                  <motion.div
                    key={en}
                    className="score-component"
                    initial={{
                      opacity: 0,
                      x: -12,
                    }}
                    animate={{
                      opacity: step >= 1 ? 1 : 0,
                      x: step >= 1 ? 0 : -12,
                    }}
                    transition={{
                      delay:
                        groupIndex * 0.12 +
                        index * 0.045,
                    }}
                  >
                    <span className="component-index">
                      {String(index + 1).padStart(2, '0')}
                    </span>

                    <div>
                      <small>{en}</small>
                      <strong>{ko}</strong>
                    </div>

                    <span className="component-scale">
                      0 — 100
                    </span>
                  </motion.div>
                ))}
              </div>
            </motion.article>
          ))}
        </div>
      </motion.section>

      <AnimatePresence>
        {step === 1 && (
          <motion.aside
            className="goodness-contract"
            initial={{
              opacity: 0,
              y: 20,
            }}
            animate={{
              opacity: 1,
              y: 0,
            }}
            transition={{ duration: 0.65 }}
          >
            <div className="goodness-main">
              <small>SCORING CONTRACT</small>

              <strong>
                0
                <span>→</span>
                100
              </strong>

              <p>
                모든 평가 요소는
                <em> 높을수록 좋은 값</em>으로 통일
              </p>
            </div>

            <div className="unknown-rule">
              <span>?</span>

              <div>
                <small>UNKNOWN ≠ ZERO</small>
                <strong>
                  확인되지 않은 값은
                  <br />
                  억지로 0점 처리하지 않습니다.
                </strong>
              </div>
            </div>
          </motion.aside>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {step === 2 && (
          <motion.section
            className="score-context-panel"
            initial={{
              opacity: 0,
              x: 25,
            }}
            animate={{
              opacity: 1,
              x: 0,
            }}
            transition={{ duration: 0.7 }}
          >
            <div className="context-column">
              <div className="context-heading">
                <small>WHO</small>
                <h3>6개 사용자 프로필</h3>
              </div>

              <div className="profile-chip-grid">
                {profiles.map((profile, index) => (
                  <motion.span
                    key={profile}
                    className={
                      profile === '고령자'
                        ? 'score-chip-active'
                        : 'score-chip-inactive'
                    }
                    initial={{
                      opacity: 0,
                      scale: 0.9,
                    }}
                    animate={{
                      opacity: 1,
                      scale: 1,
                    }}
                    transition={{
                      delay: index * 0.05,
                    }}
                  >
                    {profile}
                  </motion.span>
                ))}
              </div>
            </div>

            <div className="context-divider" />

            <div className="context-column">
              <div className="context-heading">
                <small>THIS TRIP</small>
                <h3>이번 이동 조건</h3>
              </div>

              <div className="option-chip-grid">
                {options.map((option, index) => (
                  <motion.span
                    key={option}
                    className="score-chip-inactive"
                    initial={{
                      opacity: 0,
                      scale: 0.9,
                    }}
                    animate={{
                      opacity: 1,
                      scale: 1,
                    }}
                    transition={{
                      delay: index * 0.04,
                    }}
                  >
                    {option}
                  </motion.span>
                ))}
              </div>
            </div>
          </motion.section>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {step === 3 && (
          <motion.section
            className="score-equation"
            initial={{
              opacity: 0,
              y: 24,
            }}
            animate={{
              opacity: 1,
              y: 0,
            }}
            transition={{
              duration: 0.75,
              ease: [0.22, 1, 0.36, 1],
            }}
          >
            <div>
              <small>ROUTE COMPONENTS</small>
              <strong>경로별 평가값</strong>
            </div>

            <span>×</span>

            <div className="equation-accent">
              <small>WEIGHTS</small>
              <strong>프로필 · 옵션 가중치</strong>
            </div>

            <span>→</span>

            <div className="final-score-box">
              <small>FINAL SCORE</small>
              <strong>0 — 100</strong>
              <p>후보군 내 맞춤 적합 지수</p>
            </div>
          </motion.section>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {step >= 4 && (
          <motion.section
            className="score-final-message"
            initial={{
              opacity: 0,
              scale: 0.96,
            }}
            animate={{
              opacity: 1,
              scale: 1,
            }}
            transition={{ duration: 0.7 }}
          >
            <p>IMPORTANT</p>

            <h2>
              이 점수는 확률이 아닙니다.
              <br />
              <em>후보 경로를 비교하기 위한 적합 지수입니다.</em>
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
