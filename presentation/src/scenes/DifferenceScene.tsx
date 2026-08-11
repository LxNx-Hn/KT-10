import { AnimatePresence, motion } from 'framer-motion';

interface DifferenceSceneProps {
  step: number;
}

const baseFacts = [
  '소요 시간',
  '도보 거리',
  '환승',
  '교통수단',
  '경로 형상',
];

const dongnetContext = [
  '90m 지형 경사',
  '9개 공간 레이어',
  '건물 그늘',
  '날씨 · 대기',
  '승강기',
  '저상버스',
  '보행 부담',
  '사용자 프로필',
];

export function DifferenceScene({
  step,
}: DifferenceSceneProps) {
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
              THE SIMPLE QUESTION
            </p>

            <h2>
              “그래서,
              <br />
              <em>그냥 길찾기랑 뭐가 다른데?</em>”
            </h2>
          </motion.section>
        )}
      </AnimatePresence>

      <motion.section
        className="difference-board"
        initial={{ opacity: 0 }}
        animate={{
          opacity:
            step >= 1 && step < 4
              ? 1
              : step >= 4
                ? 0.08
                : 0,
        }}
        transition={{ duration: 0.65 }}
      >
        <article className="difference-column difference-base">
          <div className="difference-column-heading">
            <small>ROUTE PROVIDER</small>
            <h3>경로 후보</h3>
            <p>
              실제 이동 가능한 길에 대한
              <br />
              기본 사실을 제공합니다.
            </p>
          </div>

          <div className="difference-fact-list">
            {baseFacts.map((fact, index) => (
              <motion.div
                key={fact}
                initial={{
                  opacity: 0,
                  x: -15,
                }}
                animate={{
                  opacity: step >= 1 ? 1 : 0,
                  x: step >= 1 ? 0 : -15,
                }}
                transition={{
                  delay: index * 0.07,
                }}
              >
                <span>0{index + 1}</span>
                <strong>{fact}</strong>
              </motion.div>
            ))}
          </div>
        </article>

        <div className="difference-bridge">
          <motion.span
            initial={{
              scaleX: 0,
            }}
            animate={{
              scaleX: step >= 2 ? 1 : 0,
            }}
            transition={{
              duration: 0.8,
            }}
          />
          <strong>+</strong>
        </div>

        <article
          className={`difference-column difference-dongnet ${
            step >= 2 ? 'visible' : ''
          }`}
        >
          <div className="difference-column-heading">
            <small>DONGNET CONTEXT</small>
            <h3>길 위의 맥락</h3>
            <p>
              후보 위에 실제 이동 환경과
              <br />
              사용자 조건을 더합니다.
            </p>
          </div>

          <div className="dongnet-context-grid">
            {dongnetContext.map((item, index) => (
              <motion.div
                key={item}
                initial={{
                  opacity: 0,
                  scale: 0.9,
                }}
                animate={{
                  opacity: step >= 2 ? 1 : 0,
                  scale: step >= 2 ? 1 : 0.9,
                }}
                transition={{
                  delay: index * 0.05,
                }}
              >
                <span className="context-pulse" />
                <strong>{item}</strong>
              </motion.div>
            ))}
          </div>
        </article>
      </motion.section>

      <AnimatePresence>
        {step >= 3 && (
          <motion.div
            className="difference-personalize"
            initial={{
              opacity: 0,
              y: 20,
            }}
            animate={{
              opacity: 1,
              y: 0,
            }}
            transition={{ duration: 0.65 }}
          >
            <div>
              <small>SAME CANDIDATES</small>
              <strong>A · B · C · D · E</strong>
            </div>

            <span>→</span>

            <div className="persona-switch">
              <small>GENERAL</small>
              <strong>일반</strong>
            </div>

            <span>→</span>

            <div>
              <small>PERSONALIZED RANKING</small>
              <strong>후보군 비교</strong>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {step >= 4 && (
          <motion.section
            className="difference-ending"
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
            <small>THE DIFFERENCE</small>

            <h2>
              지도는 <span>길을 찾고,</span>
              <br />
              동넷은 <em>나에게 맞는 길을 고릅니다.</em>
            </h2>

            <p>
              경로 생성이 아니라,
              경로 위의 맥락을 해석하고 비교하는 서비스.
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
