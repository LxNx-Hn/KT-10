import { AnimatePresence, motion } from 'framer-motion';
import { goldenDemo } from '../data/goldenDemo';
import { stepSwap, useMotionVariants } from '../motion/stepSwap';

interface LiveDemoSceneProps {
  step: number;
}

const GENERAL_CAPTURE =
  '/demo/golden-general-first.png';

const ELDERLY_CAPTURE =
  '/demo/golden-elderly-first.png';

export function LiveDemoScene({
  step,
}: LiveDemoSceneProps) {
  const motionVars = useMotionVariants();

  return (
    <main className="live-scene product-light real-demo-scene">
      <div className="live-light live-light-a" />
      <div className="live-light live-light-b" />

      <div className="presentation-hud">
        <span>06</span>
        <span className="hud-line" />
        <span>LIVE PRODUCT</span>
      </div>

      <AnimatePresence mode="wait">
        {step === 0 && (
          <motion.section
            key="live-intro"
            className="live-intro"
            {...stepSwap}
          >
            <motion.p
              className="copy-kicker"
              variants={motionVars.fadeIn}
              initial="hidden"
              animate="show"
            >
              ENOUGH EXPLANATION.
            </motion.p>

            <h2>
              <motion.span variants={motionVars.softRise} initial="hidden" animate="show">
                이제,
              </motion.span>
              <br />
              <motion.span variants={motionVars.softRise} initial="hidden" animate="show">
                <em>직접 보여드리겠습니다.</em>
              </motion.span>
            </h2>

            <motion.p
              variants={motionVars.fadeIn}
              initial="hidden"
              animate="show"
            >
              같은 출발지와 목적지에서
              <br />
              프로필만 바꿔보겠습니다.
            </motion.p>
          </motion.section>
        )}
      </AnimatePresence>

      {step >= 1 && (
        <div className="real-demo-layout">
          <motion.section
            className="real-demo-context"
            initial={{ opacity: 0, x: -16 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{
              duration: 0.36,
              ease: [0.22, 1, 0.36, 1],
            }}
          >
            <p className="real-demo-kicker">
              ACTUAL SERVICE · SAME OD
            </p>

            <div className="real-demo-od">
              <strong>
                {goldenDemo.od.origin}
              </strong>

              <span>→</span>

              <strong>
                {goldenDemo.od.destination}
              </strong>
            </div>

            <div className="real-demo-condition">
              <small>ONLY CHANGE</small>

              <strong>
                일반 프로필
                <span>→</span>
                고령자 프로필
              </strong>
            </div>
          </motion.section>

          <div className="real-device-slot">
            <motion.div
              className="real-device-motion"
              initial={{ opacity: 0, y: 18, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{
                duration: 0.42,
                ease: [0.22, 1, 0.36, 1],
              }}
            >
              <div className="real-device-frame">
                <div className="real-device-label">
                  <span className="live-status" />

                  <AnimatePresence mode="wait">
                    <motion.strong
                      key={step >= 2 ? 'ELDERLY' : 'GENERAL'}
                      variants={motionVars.numberReveal}
                      initial="hidden"
                      animate="show"
                    >
                      {step >= 2 ? 'ELDERLY' : 'GENERAL'}
                    </motion.strong>
                  </AnimatePresence>

                  <small>dongnet.kr</small>
                </div>

                <div className="real-device-screen">
                  <AnimatePresence mode="sync">
                    <motion.img
                      key={
                        step >= 2
                          ? 'elderly'
                          : 'general'
                      }
                      src={
                        step >= 2
                          ? ELDERLY_CAPTURE
                          : GENERAL_CAPTURE
                      }
                      alt={
                        step >= 2
                          ? '고령자 프로필 동넷 실제 추천 결과'
                          : '일반 프로필 동넷 실제 추천 결과'
                      }
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      transition={{ duration: 0.32 }}
                    />
                  </AnimatePresence>
                </div>
              </div>

              <motion.div
                className="real-proof-badge"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.42, duration: 0.28 }}
              >
                <span />
                ACTUAL SERVICE CAPTURE
              </motion.div>
            </motion.div>
          </div>

          <AnimatePresence mode="wait">
            {step === 1 && (
              <motion.section
                key="general-proof"
                className="real-demo-result"
                initial={{ opacity: 0, x: 16 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
              >
                <motion.div
                  className="layout-fill"
                  variants={motionVars.staggerContainer}
                  initial="hidden"
                  animate="show"
                >
                  <motion.small variants={motionVars.fadeIn}>
                    GENERAL · 1ST
                  </motion.small>

                  <motion.h3 variants={motionVars.softRise}>
                    도보 + 168 + 도시철도
                  </motion.h3>

                  <div className="real-result-metrics">
                    <motion.div variants={motionVars.numberReveal}>
                      <strong>69</strong>
                      <span>분</span>
                    </motion.div>

                    <motion.div variants={motionVars.numberReveal}>
                      <strong>1,252</strong>
                      <span>m 도보</span>
                    </motion.div>

                    <motion.div variants={motionVars.numberReveal}>
                      <strong>55</strong>
                      <span>적합도</span>
                    </motion.div>
                  </div>

                  <motion.p variants={motionVars.fadeIn}>
                    일반 프로필에서는
                    <br />
                    이 경로가 1위입니다.
                  </motion.p>
                </motion.div>
              </motion.section>
            )}

            {step >= 2 && (
              <motion.section
                key="elderly-proof"
                className="real-demo-result real-demo-result-elderly"
                initial={{ opacity: 0, x: 16 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
              >
                <motion.div
                  className="layout-fill"
                  variants={motionVars.staggerContainer}
                  initial="hidden"
                  animate="show"
                >
                  <motion.small variants={motionVars.fadeIn}>
                    ELDERLY · 1ST
                  </motion.small>

                  <motion.h3 variants={motionVars.softRise}>
                    도보 + 도시철도 + 1001
                  </motion.h3>

                  <div className="real-result-metrics">
                    <motion.div variants={motionVars.numberReveal}>
                      <strong>77</strong>
                      <span>분</span>
                    </motion.div>

                    <motion.div variants={motionVars.numberReveal}>
                      <strong>1,068</strong>
                      <span>m 도보</span>
                    </motion.div>

                    <motion.div variants={motionVars.numberReveal}>
                      <strong>36</strong>
                      <span>적합도</span>
                    </motion.div>
                  </div>

                  <motion.div
                    className="real-rank-shift"
                    variants={motionVars.softRise}
                  >
                    <div>
                      <small>GENERAL</small>
                      <strong>3위</strong>
                    </div>

                    <span>→</span>

                    <div>
                      <small>ELDERLY</small>
                      <strong>1위</strong>
                    </div>
                  </motion.div>

                  <motion.p variants={motionVars.fadeIn}>
                    같은 후보 C가
                    <br />
                    <b>일반 3위 → 고령자 1위</b>로
                    올라왔습니다.
                  </motion.p>
                </motion.div>
              </motion.section>
            )}
          </AnimatePresence>
        </div>
      )}

      <AnimatePresence>
        {step >= 1 && (
          <div className="real-live-url-slot">
            <motion.div
              className="live-url real-live-url"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ duration: 0.3, delay: 0.36 }}
            >
              <span className="live-status" />

              <div>
                <small>LIVE SERVICE</small>
                <strong>dongnet.kr</strong>
              </div>
            </motion.div>
          </div>
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
