import { AnimatePresence, motion } from 'framer-motion';
import { stepSwap, useMotionVariants } from '../motion/stepSwap';

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
    value: 'PWA',
    label: '서비스 배포',
    en: 'LIVE WEB SERVICE',
  },
];

const productScreens = [
  {
    src: `${import.meta.env.BASE_URL}app/mobile-search.webp`,
    no: '01',
    title: '검색',
    en: 'SEARCH',
  },
  {
    src: `${import.meta.env.BASE_URL}app/mobile-routes.webp`,
    no: '02',
    title: '맞춤 경로 비교',
    en: 'COMPARE',
  },
  {
    src: `${import.meta.env.BASE_URL}app/mobile-detail.webp`,
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
            key="proof-intro"
            className="proof-intro"
            {...stepSwap}
          >
            <motion.p
              className="copy-kicker"
              variants={motionVars.fadeIn}
              initial="hidden"
              animate="show"
            >
              LIVE SERVICE
            </motion.p>

            <h2>
              <motion.span variants={motionVars.softRise} initial="hidden" animate="show">
                실제 서비스로
              </motion.span>
              <br />
              <motion.span variants={motionVars.softRise} initial="hidden" animate="show">
                <em>구현하고 검증했습니다.</em>
              </motion.span>
            </h2>

            <motion.p
              variants={motionVars.fadeIn}
              initial="hidden"
              animate="show"
            >
              경로 데이터부터 사용자 경험,
              <br />
              검증과 운영 환경까지.
            </motion.p>
          </motion.section>
        )}

        {step === 1 && (
          <motion.section
            key="proof-metrics"
            className="proof-metrics-stage"
            {...stepSwap}
          >
            <motion.div
              className="proof-section-heading"
              variants={motionVars.softRise}
              initial="hidden"
              animate="show"
            >
              <small>BUILT AS A SERVICE</small>
              <h2>
                검색부터 추천 설명까지,
                {' '}
                <em>서비스 전체를 구현했습니다.</em>
              </h2>
            </motion.div>

            <motion.div
              className="proof-metrics-grid"
              variants={motionVars.staggerContainer}
              initial="hidden"
              animate="show"
            >
              {metrics.map((metric) => (
                <motion.article
                  key={metric.label}
                  variants={motionVars.numberReveal}
                >
                  <small>{metric.en}</small>
                  <strong>{metric.value}</strong>
                  <span>{metric.label}</span>
                  <div className="metric-rule" />
                </motion.article>
              ))}
            </motion.div>

            <motion.p
              className="proof-metric-note"
              variants={motionVars.fadeIn}
              initial="hidden"
              animate="show"
            >
              6개 사용자 프로필과 9개 공간 데이터 레이어를 연결하고,
              검색부터 추천·설명까지 E2E 흐름을 실제 서비스로 구현했습니다.
            </motion.p>
          </motion.section>
        )}

        {step === 2 && (
          <motion.section
            key="proof-product"
            className="proof-product-stage"
            {...stepSwap}
          >
            <div className="proof-product-copy">
              <small>FROM MODEL TO EXPERIENCE</small>

              <h2>
                추천 결과를
                <br />
                <em>
                  <span className="presentation-nowrap">
                    사용자가 이해할 수 있는
                  </span>
                  <br />
                  경험으로.
                </em>
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

        {step === 3 && (
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
                데이터 계약과 API 스키마를 기준으로
                <br />
                <em>각 영역을 연결하고 통합 검증했습니다.</em>
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
                    ['01', 'DA', '피처 · 평가 · Ranker'],
                    ['02', 'Backend', 'API 계약 · 데이터 통합'],
                    ['03', 'Frontend', '접근성 UI · 경로 시각화'],
                    ['04', 'QA', '프로필 · E2E 검증'],
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

        {step === 4 && (
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

        {step >= 5 && (
          <motion.section
            key="proof-live"
            className="proof-live-result"
            {...stepSwap}
          >
            <motion.div
              className="proof-live-label"
              variants={motionVars.fadeIn}
              initial="hidden"
              animate="show"
            >
              <span />
              LIVE PWA SERVICE
            </motion.div>

            <h2>
              <motion.span variants={motionVars.softRise} initial="hidden" animate="show">
                그리고 지금,
              </motion.span>
              <br />
              <motion.span variants={motionVars.softScale} initial="hidden" animate="show">
                <em>dongnet.kr에서 동작하고 있습니다.</em>
              </motion.span>
            </h2>

            <motion.p
              variants={motionVars.fadeIn}
              initial="hidden"
              animate="show"
            >
              PWA로 실제 서비스 흐름을 검증했고,
              프로필별 경로 추천을 운영하고 있습니다.
            </motion.p>
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
