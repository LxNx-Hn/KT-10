import { AnimatePresence, motion } from 'framer-motion';
import { stepSwap } from '../motion/stepSwap';

interface DongNetRevealSceneProps {
  step: number;
}

const dataNodes = [
  { label: '경사', sub: 'SLOPE', x: '15%', y: '28%', delay: 0.05 },
  { label: '승강기', sub: 'ELEVATOR', x: '29%', y: '67%', delay: 0.12 },
  { label: '저상버스', sub: 'LOW FLOOR', x: '43%', y: '23%', delay: 0.19 },
  { label: '단차', sub: 'CURB', x: '60%', y: '70%', delay: 0.26 },
  { label: '그늘', sub: 'SHADE', x: '72%', y: '27%', delay: 0.33 },
  { label: '계단', sub: 'STAIRS', x: '82%', y: '57%', delay: 0.4 },
  { label: '날씨', sub: 'WEATHER', x: '91%', y: '34%', delay: 0.47 },
];

const flowLines = [
  'M 220 270 C 470 300, 600 390, 800 450',
  'M 420 630 C 565 560, 690 500, 800 450',
  'M 690 225 C 720 300, 765 365, 800 450',
  'M 985 650 C 915 565, 850 505, 800 450',
  'M 1160 260 C 1010 320, 900 380, 800 450',
  'M 1325 525 C 1110 510, 930 485, 800 450',
  'M 1450 325 C 1180 365, 970 405, 800 450',
];

export function DongNetRevealScene({
  step,
}: DongNetRevealSceneProps) {
  return (
    <main className="reveal-scene">
      <div className="reveal-grid" />
      <div className="reveal-ambient reveal-ambient-left" />
      <div className="reveal-ambient reveal-ambient-right" />

      <div className="presentation-hud">
        <span>04</span>
        <span className="hud-line" />
        <span>HOW DONGNET SEES A ROUTE</span>
      </div>

      <AnimatePresence mode="wait">
        {step === 0 && (
          <motion.section
            key="reveal-intro"
            className="reveal-intro"
            {...stepSwap}
          >
            <p className="copy-kicker">SO, WHAT SHOULD A MAP SEE?</p>

            <h2>
              동넷은 사람과
              <br />
              길 위의 조건을 함께 봅니다.
            </h2>

            <p>
              경사 · 계단 · 승강기 · 그늘처럼
              <br />
              사용자 조건이 경로 평가에 들어갑니다.
            </p>
          </motion.section>
        )}
      </AnimatePresence>

      <motion.div
        className="reveal-data-stage"
        initial={{ opacity: 0 }}
        animate={{ opacity: step >= 1 ? 1 : 0 }}
        transition={{ duration: 0.65 }}
      >
        <svg
          className="reveal-flow-svg"
          viewBox="0 0 1600 900"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          {flowLines.map((path, index) => (
            <motion.path
              key={path}
              d={path}
              className="reveal-flow-line"
              initial={{ pathLength: 0, opacity: 0 }}
              animate={{
                pathLength: step >= 1 ? 1 : 0,
                opacity: step >= 1 ? 0.35 : 0,
              }}
              transition={{
                duration: 1.1,
                delay: index * 0.04,
                ease: [0.22, 1, 0.36, 1],
              }}
            />
          ))}
        </svg>

        {dataNodes.map((node) => (
          <motion.div
            key={node.label}
            className="reveal-data-node"
            style={{
              left: node.x,
              top: node.y,
            }}
            initial={{
              opacity: 0,
              scale: 0.7,
            }}
            animate={{
              opacity: step >= 1 ? 1 : 0,
              scale: step >= 1 ? 1 : 0.7,
            }}
            transition={{
              delay: step >= 1 ? node.delay : 0,
              duration: 0.55,
              ease: [0.22, 1, 0.36, 1],
            }}
          >
            <span className="data-node-pulse" />

            <div>
              <small>{node.sub}</small>
              <strong>{node.label}</strong>
            </div>
          </motion.div>
        ))}

        <motion.div
          className="reveal-core"
          initial={{
            opacity: 0,
            scale: 0.65,
          }}
          animate={{
            opacity: step >= 1 ? 1 : 0,
            scale: step >= 1 ? 1 : 0.65,
          }}
          transition={{
            type: 'spring',
            stiffness: 135,
            damping: 18,
            delay: step >= 1 ? 0.35 : 0,
          }}
        >
          <motion.div
            className="reveal-core-ring reveal-core-ring-a"
            animate={
              step >= 1
                ? { rotate: 360 }
                : { rotate: 0 }
            }
            transition={{
              duration: 18,
              repeat: Infinity,
              ease: 'linear',
            }}
          />

          <motion.div
            className="reveal-core-ring reveal-core-ring-b"
            animate={
              step >= 1
                ? { rotate: -360 }
                : { rotate: 0 }
            }
            transition={{
              duration: 13,
              repeat: Infinity,
              ease: 'linear',
            }}
          />

          <span className="reveal-core-dot" />

          <small>ROUTE CONTEXT</small>
          <strong>DONGNET</strong>
        </motion.div>
      </motion.div>

      <AnimatePresence>
        {step >= 2 && (
          <motion.div
            key="reveal-finale"
            className={`reveal-finale${step >= 3 ? ' is-split' : ''}`}
            initial={{ opacity: 0 }}
            animate={{
              opacity: 1,
              visibility: 'visible',
              pointerEvents: 'auto',
            }}
            exit={{
              opacity: 0,
              visibility: 'hidden',
              pointerEvents: 'none',
            }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          >
            <section className="dongnet-reveal-title">
              <div className="dongnet-wordmark">
                <span className="dongnet-mark" />

                <div>
                  <p>DONGNET</p>
                  <small>동넷</small>
                </div>
              </div>

              <h2>
                <span>길을 찾는 것에서,</span>
                <span>
                  <em>나에게 맞는 길을 고르는 것으로.</em>
                </span>
              </h2>
            </section>

            {step >= 3 ? (
              <div className="reveal-final-model">
                <div className="model-block">
                  <small>01</small>
                  <strong>후보 경로 수집</strong>
                  <span className="model-block-sub">ODsay · TMAP · ORS</span>
                </div>

                <span className="model-arrow">+</span>

                <div className="model-block">
                  <small>02</small>
                  <strong>길 위의 데이터</strong>
                </div>

                <span className="model-arrow">+</span>

                <div className="model-block">
                  <small>03</small>
                  <strong>사용자 조건</strong>
                </div>

                <span className="model-arrow model-arrow-result">→</span>

                <div className="model-block model-block-highlight">
                  <small>DONGNET</small>
                  <strong>맞춤 적합도 비교</strong>
                </div>
              </div>
            ) : null}
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
