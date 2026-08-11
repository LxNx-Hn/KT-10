import { AnimatePresence, motion } from 'framer-motion';

interface BuiltSceneProps {
  step: number;
}

const metrics = [
  {
    value: '6',
    label: '사용자 프로필',
    en: 'USER PROFILES',
  },
  {
    value: '9',
    label: '공간 데이터 레이어',
    en: 'SPATIAL LAYERS',
  },
  {
    value: 'E2E',
    label: '검색 → 추천 → 설명',
    en: 'END-TO-END SERVICE',
  },
  {
    value: '460',
    label: '전체 테스트',
    en: 'TOTAL TESTS',
  },
];

const productScreens = [
  {
    src: '/app/mobile-search.webp',
    no: '01',
    title: '검색',
    en: 'SEARCH',
  },
  {
    src: '/app/mobile-routes.webp',
    no: '02',
    title: '맞춤 경로 비교',
    en: 'COMPARE',
  },
  {
    src: '/app/mobile-detail.webp',
    no: '03',
    title: '추천 이유 확인',
    en: 'UNDERSTAND',
  },
];

const ciLanes = [
  {
    name: 'AI',
    detail: 'Test · Lint · Security · Audit',
    items: ['Pytest', 'Ruff', 'Bandit', 'pip-audit'],
  },
  {
    name: 'BACKEND',
    detail: 'Test · Migration · Security',
    items: ['Pytest', 'Alembic', 'Bandit', 'pip-audit'],
  },
  {
    name: 'FRONTEND',
    detail: 'Test · Build · Accessibility',
    items: ['Unit', 'Build', 'Playwright A11y', 'npm audit'],
  },
  {
    name: 'PRODUCTION',
    detail: 'Build · Runtime · Health',
    items: ['Docker', 'Compose', 'Healthz', 'Readiness'],
  },
];

export function BuiltScene({
  step,
}: BuiltSceneProps) {
  return (
    <main className="built-scene product-light">
      <div className="proof-grid-bg" />
      <div className="proof-blue-glow" />
      <div className="proof-green-glow" />

      <div className="presentation-hud">
        <span>11</span>
        <span className="hud-line" />
        <span>BUILT & VALIDATED</span>
      </div>

      <AnimatePresence mode="wait">
        {step === 0 && (
          <motion.section
            key="proof-intro"
            className="proof-intro"
            initial={{
              opacity: 0,
              y: 28,
            }}
            animate={{
              opacity: 1,
              y: 0,
            }}
            exit={{
              opacity: 0,
              y: -18,
            }}
            transition={{ duration: 0.7 }}
          >
            <p className="copy-kicker">
              NOT JUST A CONCEPT.
            </p>

            <h2>
              아이디어에서 끝내지 않고,
              <br />
              <em>실제 서비스로 연결했습니다.</em>
            </h2>

            <p>
              경로 데이터부터 사용자 경험,
              <br />
              검증과 운영 환경까지.
            </p>
          </motion.section>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {step === 1 && (
          <motion.section
            className="proof-metrics-stage"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.6 }}
          >
            <div className="proof-section-heading">
              <small>BUILT AS A SERVICE</small>
              <h2>
                하나의 기능이 아니라,
                <em> 서비스 전체를 구현했습니다.</em>
              </h2>
            </div>

            <div className="proof-metrics-grid">
              {metrics.map((metric, index) => (
                <motion.article
                  key={metric.label}
                  initial={{
                    opacity: 0,
                    y: 26,
                  }}
                  animate={{
                    opacity: 1,
                    y: 0,
                  }}
                  transition={{
                    duration: 0.65,
                    delay: index * 0.09,
                  }}
                >
                  <small>{metric.en}</small>

                  <motion.strong
                    initial={{
                      opacity: 0,
                      scale: 0.88,
                    }}
                    animate={{
                      opacity: 1,
                      scale: 1,
                    }}
                    transition={{
                      delay: 0.15 + index * 0.09,
                      duration: 0.6,
                    }}
                  >
                    {metric.value}
                  </motion.strong>

                  <span>{metric.label}</span>

                  <div className="metric-rule" />
                </motion.article>
              ))}
            </div>

            <p className="proof-metric-note">
              6개 사용자 프로필과 9개 공간 데이터 레이어를 연결하고,
              검색부터 추천·설명까지 E2E 흐름을 구현한 뒤 테스트로 검증했습니다.
            </p>
          </motion.section>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {step === 2 && (
          <motion.section
            className="proof-product-stage"
            initial={{
              opacity: 0,
              y: 20,
            }}
            animate={{
              opacity: 1,
              y: 0,
            }}
            exit={{
              opacity: 0,
            }}
            transition={{ duration: 0.7 }}
          >
            <div className="proof-product-copy">
              <small>FROM MODEL TO EXPERIENCE</small>

              <h2>
                추천 결과를
                <br />
                <em>사용자가 이해할 수 있는 경험으로.</em>
              </h2>

              <p>
                검색하고, 조건을 설정하고,
                <br />
                경로를 비교하고, 추천 이유까지 확인합니다.
              </p>

              <div className="proof-product-flow">
                <span>SEARCH</span>
                <i>→</i>
                <span>PERSONALIZE</span>
                <i>→</i>
                <span>COMPARE</span>
                <i>→</i>
                <span>UNDERSTAND</span>
              </div>
            </div>

            <div className="proof-devices">
              {productScreens.map((screen, index) => (
                <motion.figure
                  key={screen.no}
                  initial={{
                    opacity: 0,
                    y: 30,
                    rotate: index === 0 ? -3 : index === 2 ? 3 : 0,
                  }}
                  animate={{
                    opacity: 1,
                    y: index === 1 ? -20 : 8,
                    rotate: index === 0 ? -3 : index === 2 ? 3 : 0,
                  }}
                  transition={{
                    delay: index * 0.1,
                    duration: 0.75,
                    ease: [0.22, 1, 0.36, 1],
                  }}
                >
                  <div className="proof-device-shell">
                    <img
                      src={screen.src}
                      alt={screen.title}
                    />
                  </div>

                  <figcaption>
                    <small>{screen.en}</small>
                    <strong>{screen.title}</strong>
                  </figcaption>
                </motion.figure>
              ))}
            </div>
          </motion.section>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {step === 3 && (
          <motion.section
            className="proof-ci-stage"
            initial={{
              opacity: 0,
              y: 22,
            }}
            animate={{
              opacity: 1,
              y: 0,
            }}
            exit={{
              opacity: 0,
            }}
            transition={{ duration: 0.7 }}
          >
            <div className="proof-ci-heading">
              <small>CONTINUOUS VALIDATION</small>

              <h2>
                구현한 뒤에도,
                <br />
                <em>자동으로 다시 검증합니다.</em>
              </h2>

              <p>
                AI · Backend · Frontend · Production의
                품질 게이트를 GitHub Actions에서 검사합니다.
              </p>
            </div>

            <div className="proof-ci-board">
              {ciLanes.map((lane, index) => (
                <motion.article
                  key={lane.name}
                  initial={{
                    opacity: 0,
                    x: 24,
                  }}
                  animate={{
                    opacity: 1,
                    x: 0,
                  }}
                  transition={{
                    delay: index * 0.09,
                    duration: 0.6,
                  }}
                >
                  <div className="ci-lane-main">
                    <span className="ci-status-dot" />

                    <div>
                      <small>{lane.detail}</small>
                      <strong>{lane.name}</strong>
                    </div>

                    <span className="ci-pass">
                      PASS
                    </span>
                  </div>

                  <div className="ci-items">
                    {lane.items.map((item) => (
                      <span key={item}>
                        {item}
                      </span>
                    ))}
                  </div>

                  <motion.div
                    className="ci-progress"
                    initial={{ scaleX: 0 }}
                    animate={{ scaleX: 1 }}
                    transition={{
                      delay: 0.18 + index * 0.09,
                      duration: 0.9,
                    }}
                  />
                </motion.article>
              ))}
            </div>

            <div className="proof-ci-footer">
              <div>
                <small>PIPELINE</small>
                <strong>GitHub Actions</strong>
              </div>

              <span>→</span>

              <div>
                <small>QUALITY GATES</small>
                <strong>4</strong>
              </div>

              <span>→</span>

              <div className="ci-footer-accent">
                <small>PRODUCTION VALIDATION</small>
                <strong>READY</strong>
              </div>
            </div>
          </motion.section>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {step >= 4 && (
          <motion.section
            className="proof-live-result"
            initial={{
              opacity: 0,
              scale: 0.96,
            }}
            animate={{
              opacity: 1,
              scale: 1,
            }}
            transition={{
              duration: 0.75,
              ease: [0.22, 1, 0.36, 1],
            }}
          >
            <div className="proof-live-label">
              <span />
              LIVE SERVICE
            </div>

            <h2>
              그리고 지금,
              <br />
              <em>dongnet.kr에서 동작하고 있습니다.</em>
            </h2>

            <p>
              데이터 → 추천 → 사용자 경험까지,
              하나의 서비스로 연결했습니다.
            </p>
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
