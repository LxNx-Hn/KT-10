import { AnimatePresence, motion } from 'framer-motion';
import { stepSwap, useMotionVariants } from '../motion/stepSwap';

interface BuiltSceneProps {
  step: number;
}

const productScreens = [
  {
    src: `${import.meta.env.BASE_URL}app/kt-search.png`,
    no: '01',
    title: '검색',
    en: 'SEARCH',
  },
  {
    src: `${import.meta.env.BASE_URL}app/kt-route-compare.png`,
    no: '02',
    title: '프로필별 추천 비교',
    en: 'COMPARE',
  },
  {
    src: `${import.meta.env.BASE_URL}app/kt-route-detail.png`,
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
  const motionVars = useMotionVariants();
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
            key="proof-product"
            className="proof-product-stage"
            {...stepSwap}
          >
            <div className="proof-product-copy">
              <small>FROM MODEL TO EXPERIENCE</small>

              <h2>
                검색하고 비교하고,
                <br />
                <em>
                  <span className="presentation-nowrap">
                    추천 이유까지 확인합니다.
                  </span>
                </em>
              </h2>

              <p>
                출발지와 목적지를 입력하면,
                <br />
                <span className="single-line-copy">
                  프로필에 맞는 경로를 지도와 카드로 비교할 수 있습니다.
                </span>
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
                    y: index === 1 ? -8 : 16,
                    rotate: index === 0 ? -3 : index === 2 ? 3 : 0,
                  }}
                  animate={{
                    opacity: 1,
                    y: index === 1 ? -20 : 8,
                    rotate: index === 0 ? -3 : index === 2 ? 3 : 0,
                  }}
                  transition={{
                    delay: index === 1 ? 0.06 : 0.18,
                    duration: 0.38,
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

        {step === 1 && (
          <motion.section
            key="proof-collab"
            className="proof-collab-stage"
            {...stepSwap}
          >
            <motion.div
              className="proof-ci-heading"
              variants={motionVars.softRise}
              initial="hidden"
              animate="show"
            >
              <small>TEAM INTEGRATION</small>

              <h2>
                DA · Backend · Frontend를 연결해,
                <br />
                <em>프로필별 서비스 흐름을 함께 점검했습니다.</em>
              </h2>
            </motion.div>

            <motion.div
              className="proof-collab-flow"
              variants={motionVars.staggerContainer}
              initial="hidden"
              animate="show"
            >
                {(
                  [
                    ['01', 'DA', '경로 피처 · 평가 · Ranker'],
                    ['02', 'Backend', '후보 경로 · 공공데이터 API'],
                    ['03', 'Frontend', '프로필 UI · 지도 시각화'],
                    ['04', 'QA', '프로필별 흐름 · E2E'],
                  ] as const
                ).flatMap(([no, title, detail], index) => {
                  const card = (
                    <motion.article key={title} variants={motionVars.softScale}>
                      <small>{no}</small>
                      <strong>{title}</strong>
                      <span>{detail}</span>
                    </motion.article>
                  );

                  if (index === 0) {
                    return [card];
                  }

                  return [
                    <motion.i
                      key={`arrow-${title}`}
                      className="motion-arrow"
                      variants={motionVars.drawLine}
                    >
                      →
                    </motion.i>,
                    card,
                  ];
                })}
              </motion.div>
          </motion.section>
        )}

        {step === 2 && (
          <motion.section
            key="proof-ci"
            className="proof-ci-stage"
            {...stepSwap}
          >
            <motion.div
              className="proof-ci-heading"
              variants={motionVars.softRise}
              initial="hidden"
              animate="show"
            >
              <small>CONTINUOUS VALIDATION</small>

              <h2>
                구현한 뒤에도,
                <br />
                <em>자동으로 다시 검증합니다.</em>
              </h2>

              <p>
                AI · Backend · Frontend · Production의
                <br />
                품질 게이트를 GitHub Actions에서 검사합니다.
              </p>

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
            </motion.div>

            <motion.div
              className="proof-ci-board"
              variants={motionVars.staggerContainer}
              initial="hidden"
              animate="show"
            >
              {ciLanes.map((lane) => (
                <motion.article
                  key={lane.name}
                  variants={motionVars.softRise}
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
                    variants={motionVars.drawLine}
                  />
                </motion.article>
              ))}
            </motion.div>
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
