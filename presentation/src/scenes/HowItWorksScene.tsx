import { AnimatePresence, motion } from 'framer-motion';
import { stepSwap, useMotionVariants } from '../motion/stepSwap';

interface HowItWorksSceneProps {
  step: number;
}

const analysisSteps = [
  '후보 경로 수집',
  '데이터 결합',
];

const candidateSources = [
  {
    name: 'ODsay',
    role: '대중교통 후보',
    note: '',
  },
  {
    name: 'TMAP',
    role: '도보 · 일반 이동 후보',
    note: '',
  },
  {
    name: 'ORS',
    role: '이동지원 후보 보완',
    note: 'wheelchair profile 지원',
  },
];

const joinLayers = [
  {
    title: '지형 · 접근성',
    items: ['90m 지형 데이터', '경사', '계단', '단차', '승강기'],
  },
  {
    title: '환경 · 편의',
    items: ['그늘', '저상버스', '안전'],
  },
  {
    title: '실시간',
    items: ['날씨', '버스 도착'],
  },
];

export function HowItWorksScene({
  step,
}: HowItWorksSceneProps) {
  const analysisStep = step - 1;
  const motionVars = useMotionVariants();

  return (
    <main className="how-scene product-light">
      <div className="how-grid" />
      <div className="how-ambient" />

      <div className="presentation-hud">
        <span>05</span>
        <span className="hud-line" />
        <span>FROM REQUEST TO RECOMMENDATION</span>
      </div>

      <AnimatePresence mode="wait">
        {step === 0 && (
          <motion.section
            key="intro"
            className="how-intro"
            {...stepSwap}
          >
            <motion.p
              className="copy-kicker"
              variants={motionVars.fadeIn}
              initial="hidden"
              animate="show"
            >
              HOW DOES IT ACTUALLY WORK?
            </motion.p>

            <h2>
              <motion.span variants={motionVars.softRise} initial="hidden" animate="show">
                API의 후보 경로와
              </motion.span>
              <br />
              <motion.span variants={motionVars.softRise} initial="hidden" animate="show">
                <em>공공 · 실시간 데이터를 결합합니다.</em>
              </motion.span>
            </h2>

            <motion.p
              variants={motionVars.fadeIn}
              initial="hidden"
              animate="show"
            >
              DongNet이 사용자별 경로 점수를 계산합니다.
            </motion.p>
          </motion.section>
        )}

        {step >= 1 && (
          <motion.section
            key="analysis"
            className="how-analysis"
            {...stepSwap}
          >
            <nav className="how-analysis-nav" aria-label="분석 단계">
              {analysisSteps.map((label, index) => (
                <span
                  key={label}
                  className={
                    index === analysisStep
                      ? 'is-active'
                      : index < analysisStep
                        ? 'is-done'
                        : ''
                  }
                >
                  0{index + 1} {label}
                </span>
              ))}
            </nav>

            <AnimatePresence mode="wait">
              {step === 1 && (
                <motion.div
                  key="candidates"
                  className="how-panel"
                  {...stepSwap}
                >
                  <motion.div
                    className="how-panel-heading"
                    variants={motionVars.softRise}
                    initial="hidden"
                    animate="show"
                  >
                    <small>STEP 01 · CANDIDATES</small>
                    <h2>
                      세 API에서 후보 경로를 수집합니다.
                    </h2>
                  </motion.div>

                  <motion.div
                    className="how-source-grid"
                    variants={motionVars.staggerContainer}
                    initial="hidden"
                    animate="show"
                  >
                    {candidateSources.map((source) => (
                      <motion.article
                        key={source.name}
                        className="how-source-card"
                        variants={motionVars.softScale}
                      >
                        <small>API</small>
                        <h3>{source.name}</h3>
                        <p>{source.role}</p>
                        {source.note ? (
                          <span className="how-source-note">
                            {source.note}
                          </span>
                        ) : null}
                      </motion.article>
                    ))}
                  </motion.div>
                </motion.div>
              )}

              {step === 2 && (
                <motion.div
                  key="join"
                  className="how-panel"
                  {...stepSwap}
                >
                  <motion.div
                    className="how-panel-heading"
                    variants={motionVars.softRise}
                    initial="hidden"
                    animate="show"
                  >
                    <small>STEP 02 · SPATIAL JOIN</small>
                    <h2>
                      후보 경로에 공공 · 실시간 데이터를 결합합니다.
                    </h2>
                  </motion.div>

                  <motion.div
                    className="how-join-layout"
                    variants={motionVars.staggerContainer}
                    initial="hidden"
                    animate="show"
                  >
                    {joinLayers.map((layer) => (
                      <motion.article
                        key={layer.title}
                        className="how-join-card"
                        variants={motionVars.softScale}
                      >
                        <h3>{layer.title}</h3>
                        <ul>
                          {layer.items.map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      </motion.article>
                    ))}
                  </motion.div>

                  <motion.div
                    className="how-join-core"
                    variants={motionVars.drawLine}
                    initial="hidden"
                    animate="show"
                  >
                    경로 구간별 공간 결합
                  </motion.div>
                </motion.div>
              )}
            </AnimatePresence>
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
