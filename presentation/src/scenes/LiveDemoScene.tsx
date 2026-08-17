import { AnimatePresence, motion } from 'framer-motion';
import { goldenDemo } from '../data/goldenDemo';

interface LiveDemoSceneProps {
  step: number;
}

const GENERAL_CAPTURE =
  `${import.meta.env.BASE_URL}demo/golden-general-first.png`;

const ELDERLY_CAPTURE =
  `${import.meta.env.BASE_URL}demo/golden-elderly-first.png`;

export function LiveDemoScene({
  step,
}: LiveDemoSceneProps) {
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
              y: -16,
            }}
            transition={{
              duration: 0.7,
            }}
          >
            <p className="copy-kicker">
              ENOUGH EXPLANATION.
            </p>

            <h2>
              이제,
              <br />
              <em>직접 보여드리겠습니다.</em>
            </h2>

            <p>
              같은 출발지와 목적지에서
              <br />
              프로필만 바꿔보겠습니다.
            </p>
          </motion.section>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {step >= 1 && (
          <motion.section
            className="real-demo-context"
            initial={{
              opacity: 0,
              x: -22,
            }}
            animate={{
              opacity: 1,
              x: 0,
            }}
            transition={{
              duration: 0.65,
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
        )}
      </AnimatePresence>

      {step >= 1 && (
        <motion.div
          className="real-device-anchor"
          initial={{
            opacity: 0,
            scale: 0.9,
            y: 32,
          }}
          animate={{
            opacity: 1,
            scale:
              step >= 2
                ? 1.015
                : 1,
            y: 0,
          }}
          transition={{
            duration: 0.8,
            ease: [0.22, 1, 0.36, 1],
          }}
        >
          <div className="real-device-frame">
            <div className="real-device-label">
              <span className="live-status" />

              <strong>
                {step >= 2
                  ? 'ELDERLY'
                  : 'GENERAL'}
              </strong>

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
                  initial={{
                    opacity: 0,
                    scale: 1.015,
                  }}
                  animate={{
                    opacity: 1,
                    scale: 1,
                  }}
                  exit={{
                    opacity: 0,
                    scale: 0.99,
                  }}
                  transition={{
                    duration: 0.55,
                  }}
                />
              </AnimatePresence>
            </div>
          </div>

          <div className="real-proof-badge">
            <span />
            ACTUAL SERVICE CAPTURE
          </div>
        </motion.div>
      )}

      <AnimatePresence mode="wait">
        {step === 1 && (
          <motion.section
            key="general-proof"
            className="real-demo-result"
            initial={{
              opacity: 0,
              x: 20,
            }}
            animate={{
              opacity: 1,
              x: 0,
            }}
            exit={{
              opacity: 0,
              x: 15,
            }}
            transition={{
              duration: 0.6,
              delay: 0.15,
            }}
          >
            <small>GENERAL · 1ST</small>

            <h3>
              도보 + 168 + 도시철도
            </h3>

            <div className="real-result-metrics">
              <div>
                <strong>69</strong>
                <span>분</span>
              </div>

              <div>
                <strong>1,252</strong>
                <span>m 도보</span>
              </div>

              <div>
                <strong>55</strong>
                <span>적합도</span>
              </div>
            </div>

            <p>
              일반 프로필에서는
              <br />
              이 경로가 1위입니다.
            </p>
          </motion.section>
        )}

        {step >= 2 && (
          <motion.section
            key="elderly-proof"
            className="real-demo-result real-demo-result-elderly"
            initial={{
              opacity: 0,
              x: 22,
            }}
            animate={{
              opacity: 1,
              x: 0,
            }}
            transition={{
              duration: 0.6,
              delay: 0.15,
            }}
          >
            <small>ELDERLY · 1ST</small>

            <h3>
              도보 + 도시철도 + 1001
            </h3>

            <div className="real-result-metrics">
              <div>
                <strong>77</strong>
                <span>분</span>
              </div>

              <div>
                <strong>1,068</strong>
                <span>m 도보</span>
              </div>

              <div>
                <strong>36</strong>
                <span>적합도</span>
              </div>
            </div>

            <div className="real-rank-shift">
              <div>
                <small>GENERAL</small>
                <strong>3위</strong>
              </div>

              <span>→</span>

              <div>
                <small>ELDERLY</small>
                <strong>1위</strong>
              </div>
            </div>

            <p>
              같은 후보 C가
              <br />
              <b>일반 3위 → 고령자 1위</b>로
              올라왔습니다.
            </p>
          </motion.section>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {step >= 1 && (
          <motion.div
            className="live-url real-live-url"
            initial={{
              opacity: 0,
              x: 15,
            }}
            animate={{
              opacity: 1,
              x: 0,
            }}
            transition={{
              duration: 0.55,
            }}
          >
            <span className="live-status" />

            <div>
              <small>LIVE SERVICE</small>
              <strong>dongnet.kr</strong>
            </div>
          </motion.div>
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
