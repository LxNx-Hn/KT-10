import { AnimatePresence, motion } from 'framer-motion';

interface DongNetRevealSceneProps {
  step: number;
}

const dataNodes = [
  { label: '경사', sub: 'SLOPE', x: '15%', y: '28%', delay: 0.05 },
  { label: '승강기', sub: 'ELEVATOR', x: '29%', y: '67%', delay: 0.12 },
  { label: '저상버스', sub: 'LOW FLOOR', x: '43%', y: '23%', delay: 0.19 },
  { label: '보행 부담', sub: 'WALK', x: '60%', y: '70%', delay: 0.26 },
  { label: '그늘', sub: 'SHADE', x: '72%', y: '27%', delay: 0.33 },
  { label: '환승', sub: 'TRANSFER', x: '82%', y: '57%', delay: 0.4 },
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
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 0.75 }}
          >
            <p className="copy-kicker">SO, WHAT SHOULD A MAP SEE?</p>

            <h2>
              길만 봐서는
              <br />
              알 수 없습니다.
            </h2>

            <p>
              이동하는 사람과,
              <br />
              그 길 위의 조건을 함께 봐야 합니다.
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
          <motion.section
            className="dongnet-reveal-title"
            initial={{
              opacity: 0,
              scale: 0.96,
              y: 18,
            }}
            animate={{
              opacity: 1,
              scale: 1,
              y: 0,
            }}
            transition={{
              duration: 0.8,
              ease: [0.22, 1, 0.36, 1],
            }}
          >
            <div className="dongnet-wordmark">
              <span className="dongnet-mark" />

              <div>
                <p>DONGNET</p>
                <small>동넷</small>
              </div>
            </div>

            <h2>
              길을 찾는 것에서,
              <br />
              <em>나에게 맞는 길을 고르는 것</em>으로.
            </h2>
          </motion.section>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {step >= 3 && (
          <motion.div
            className="reveal-final-model"
            initial={{
              opacity: 0,
              y: 26,
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
            <div className="model-block">
              <small>01</small>
              <strong>후보 경로</strong>
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
