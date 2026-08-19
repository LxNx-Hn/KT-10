import { AnimatePresence, motion } from 'framer-motion';
import { stepSwap, useMotionVariants } from '../motion/stepSwap';

interface DifferenceSceneProps {
  step: number;
}

const commercialPoints = [
  '시간 · 거리 중심',
  '다수 사용자 기준',
  '빠른 도착 중심',
];

const dongnetPoints = [
  '사용자 프로필 반영',
  '이동 부담 · 접근성 · 환경 조건 평가',
  '후보 경로 재정렬',
  '추천 이유 제공',
];

export function DifferenceScene({
  step,
}: DifferenceSceneProps) {
  const motionVars = useMotionVariants();

  return (
    <main className="difference-scene">
      <div className="difference-glow" />

      <div className="presentation-hud">
        <span>10</span>
        <span className="hud-line" />
        <span>WHAT MAKES DONGNET DIFFERENT?</span>
      </div>

      <AnimatePresence mode="wait">
        {step === 0 && (
          <motion.section
            key="diff-question"
            className="difference-question"
            {...stepSwap}
          >
            <motion.div
              className="layout-fill"
              variants={motionVars.staggerContainer}
              initial="hidden"
              animate="show"
            >
              <motion.p
                className="copy-kicker"
                variants={motionVars.fadeIn}
              >
                THE DIFFERENCE
              </motion.p>

              <h2>
                <motion.span variants={motionVars.softRise} initial="hidden" animate="show">
                  동넷은 길찾기의 기준을
                </motion.span>
                <br />
                <motion.span variants={motionVars.softRise} initial="hidden" animate="show">
                  <em>어떻게 바꿨을까요?</em>
                </motion.span>
              </h2>
            </motion.div>
          </motion.section>
        )}

        {step === 1 && (
          <motion.section
            key="diff-board"
            className="difference-board difference-board-simple"
            {...stepSwap}
          >
            <motion.article
              className="difference-column difference-base visible"
              initial={{ opacity: 0, x: -16 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.36, ease: [0.22, 1, 0.36, 1] }}
            >
              <div className="difference-column-heading">
                <small>COMMERCIAL ROUTING</small>
                <h3>상용 길찾기</h3>
              </div>

              <div className="difference-fact-list">
                {commercialPoints.map((fact, index) => (
                  <div key={fact}>
                    <span>0{index + 1}</span>
                    <strong>{fact}</strong>
                  </div>
                ))}
              </div>
            </motion.article>

            <motion.div
              className="difference-bridge"
              initial={{ opacity: 0, scaleX: 0 }}
              animate={{ opacity: 1, scaleX: 1 }}
              transition={{
                delay: 0.28,
                duration: 0.32,
                ease: [0.22, 1, 0.36, 1],
              }}
            >
              <span />
              <strong>vs</strong>
            </motion.div>

            <motion.article
              className="difference-column difference-dongnet visible"
              initial={{ opacity: 0, x: 16 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{
                duration: 0.36,
                delay: 0.08,
                ease: [0.22, 1, 0.36, 1],
              }}
            >
              <div className="difference-column-heading">
                <small>DONGNET ROUTING</small>
                <h3>DongNet</h3>
              </div>

              <div className="dongnet-context-grid dongnet-context-simple">
                {dongnetPoints.map((item) => (
                  <div key={item}>
                    <span className="context-pulse" />
                    <strong>{item}</strong>
                  </div>
                ))}
              </div>
              <p className="difference-ors-note">
                이동지원 후보는 ORS로 보완합니다.
              </p>
            </motion.article>
          </motion.section>
        )}

        {step >= 2 && (
          <motion.section
            key="diff-ending"
            className="difference-ending"
            {...stepSwap}
          >
            <motion.div
              className="layout-fill"
              variants={motionVars.staggerContainer}
              initial="hidden"
              animate="show"
            >
              <motion.small variants={motionVars.fadeIn}>
                THE DIFFERENCE
              </motion.small>

              <h2>
                상용 길찾기: <span>시간·거리 중심의 최적 경로</span>
                <br />
                DongNet: <em>이동 조건·접근성·환경 중심의 적합 경로</em>
              </h2>
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
