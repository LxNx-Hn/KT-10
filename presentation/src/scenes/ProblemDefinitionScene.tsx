import { AnimatePresence, motion } from 'framer-motion';

interface ProblemDefinitionSceneProps {
  step: number;
}

const basicFacts = [
  ['TIME', '소요 시간'],
  ['DISTANCE', '도보 거리'],
  ['TRANSFER', '환승'],
];

const mobilityConditions = [
  ['SLOPE', '경사'],
  ['STAIRS', '계단'],
  ['ELEVATOR', '승강기'],
  ['LOW FLOOR', '저상버스'],
  ['WALK', '보행 부담'],
  ['SHADE', '그늘'],
  ['WEATHER', '날씨'],
];

export function ProblemDefinitionScene({
  step,
}: ProblemDefinitionSceneProps) {
  return (
    <main className="definition-scene">
      <div className="definition-grid" />
      <div className="definition-glow" />

      <div className="presentation-hud">
        <span>03</span>
        <span className="hud-line" />
        <span>PROBLEM DEFINITION</span>
      </div>

      <AnimatePresence mode="wait">
        {step === 0 && (
          <motion.section
            className="definition-intro"
            initial={{ opacity: 0, y: 28 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -16 }}
            transition={{ duration: 0.7 }}
          >
            <p className="copy-kicker">
              THE ACTUAL PROBLEM
            </p>

            <h2>
              문제는,
              <br />
              <em>길이 없는 것이 아닙니다.</em>
            </h2>

            <p>
              같은 경로도 이동하는 사람과
              <br />
              환경에 따라 전혀 다른 길이 됩니다.
            </p>
          </motion.section>
        )}
      </AnimatePresence>

      <motion.section
        className="definition-board"
        initial={{ opacity: 0 }}
        animate={{
          opacity: step >= 1 && step < 2 ? 1 : step >= 2 ? 0.08 : 0,
        }}
        transition={{ duration: 0.65 }}
      >
        <article className="definition-basic">
          <small>ROUTE FACTS</small>
          <h3>경로의 기본 사실</h3>

          <p>
            일반적인 경로 후보에서
            <br />
            우선 확인할 수 있는 정보
          </p>

          <div className="definition-basic-list">
            {basicFacts.map(([en, ko], index) => (
              <motion.div
                key={en}
                initial={{ opacity: 0, x: -15 }}
                animate={{
                  opacity: step >= 1 ? 1 : 0,
                  x: step >= 1 ? 0 : -15,
                }}
                transition={{ delay: index * 0.09 }}
              >
                <span>0{index + 1}</span>
                <div>
                  <small>{en}</small>
                  <strong>{ko}</strong>
                </div>
              </motion.div>
            ))}
          </div>
        </article>

        <div className="definition-gap">
          <span>≠</span>
        </div>

        <article className="definition-context">
          <small>REAL MOBILITY</small>
          <h3>실제 이동을 바꾸는 조건</h3>

          <p>
            특히 이동취약자에게는
            <br />
            길 위의 조건이 이동 가능성을 바꿉니다.
          </p>

          <div className="definition-context-grid">
            {mobilityConditions.map(([en, ko], index) => (
              <motion.div
                key={en}
                initial={{
                  opacity: 0,
                  scale: 0.92,
                }}
                animate={{
                  opacity: step >= 1 ? 1 : 0.14,
                  scale: step >= 1 ? 1 : 0.92,
                }}
                transition={{
                  delay: index * 0.055,
                }}
              >
                <span />
                <small>{en}</small>
                <strong>{ko}</strong>
              </motion.div>
            ))}
          </div>
        </article>
      </motion.section>

      <AnimatePresence>
        {step >= 2 && (
          <motion.section
            className="definition-result"
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
            <small>PROBLEM STATEMENT</small>

            <h2>
              이동 가능한 경로와,
              <br />
              <em>이용하기 편한 경로 사이의 간극.</em>
            </h2>

            <div className="definition-rule" />

            <p>
              동넷은 이 간극을
              <strong> 사용자별 경로 평가</strong>로 해결합니다.
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
