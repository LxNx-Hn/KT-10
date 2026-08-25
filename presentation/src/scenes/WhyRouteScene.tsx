import { AnimatePresence, motion } from 'framer-motion';
import { goldenDemo } from '../data/goldenDemo';

interface WhyRouteSceneProps {
  step: number;
}

const candidates = goldenDemo.general.routes;

const evidence = [
  {
    en: 'RANK',
    ko: '후보 순위',
    value: '3위 → 1위',
  },
  {
    en: 'TIME',
    ko: '소요 시간',
    value: '33분 → 47분',
  },
  {
    en: 'WALK',
    ko: '도보 거리',
    value: '832m → 697m',
    delta: '-135m',
  },
  {
    en: 'SLOPE',
    ko: '평균 경사',
    value: '3.14% → 2.88%',
    delta: '-0.26%p',
  },
  {
    en: 'SHADE',
    ko: '확인된 그늘',
    value: '20% → 10%',
  },
  {
    en: 'TRANSFER',
    ko: '환승',
    value: '1회 → 0회',
  },
];

export function WhyRouteScene({
  step,
}: WhyRouteSceneProps) {
  // Remap: new 1 = old comparison (was >= 2), new 2 = old final (was >= 4)
  const showComparison = step >= 1;
  const showFinal = step >= 2;

  return (
    <main
      className={`why-scene product-light ${
        showFinal ? 'why-final-step' : ''
      }`}
    >
      <div className="why-grid" />

      <div className="presentation-hud">
        <span>07</span>
        <span className="hud-line" />
        <span>WHY THIS ROUTE?</span>
      </div>

      <AnimatePresence mode="wait">
        {step === 0 && (
          <motion.section
            key="why-intro"
            className="why-intro"
            initial={{ opacity: 0, y: 25 }}
            animate={{
              opacity: 1,
              y: 0,
              transition: { duration: 0.55 },
            }}
            exit={{
              opacity: 0,
              transition: { duration: 0.16 },
            }}
          >
            <p className="copy-kicker">
              AFTER THE LIVE DEMO
            </p>

            <h2>
              방금,
              <br />
              <em>무슨 일이 일어났을까요?</em>
            </h2>

            <p>
              프로필만 바꿨는데
              <br />
              추천 순위가 달라졌습니다.
            </p>
          </motion.section>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {step === 0 && (
          <motion.aside
            className="why-accessibility-callout"
            initial={{ opacity: 0, x: 22 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 16 }}
            transition={{ duration: 0.5, delay: 0.18 }}
          >
            <small>MOBILITY SUPPORT CHECK</small>
            <strong>계단 없는 이동 · 휠체어 경사</strong>
            <span>승강기 · 건물 진입 턱까지 함께 확인합니다.</span>
          </motion.aside>
        )}
      </AnimatePresence>

      <motion.div
        className="why-candidates"
        initial={{ opacity: 0 }}
        animate={{
          opacity: showComparison ? 1 : 0,
        }}
        transition={{
          duration: 0.45,
          delay: showComparison ? 0.12 : 0,
        }}
      >
        {candidates.map((candidate, index) => {
          const promoted =
            candidate.id ===
            goldenDemo.comparison.promotedRoute;

          return (
            <motion.article
              key={candidate.id}
              className={`candidate-card ${
                promoted && showComparison
                  ? 'candidate-promoted'
                  : ''
              }`}
              initial={{
                opacity: 0,
                y: 25,
              }}
              animate={{
                opacity: showComparison ? 1 : 0,
                y: showComparison ? 0 : 25,

                scale:
                  showComparison && promoted
                    ? 1.025
                    : showComparison
                      ? 0.94
                      : 1,
              }}
              transition={{
                duration: 0.45,
                delay: showComparison
                  ? 0.12 + index * 0.08
                  : 0,
              }}
            >
              <div className="candidate-top">
                <small>ROUTE {candidate.id}</small>

                {showComparison && promoted && (
                  <span>MOBILITY 1위</span>
                )}
              </div>

              <h3>{candidate.name}</h3>

              <div className="candidate-metrics">
                <div>
                  <small>TIME</small>
                  <strong>
                    {candidate.timeMin}분
                  </strong>
                </div>

                <div>
                  <small>WALK</small>
                  <strong>
                    {candidate.walkM.toLocaleString()}m
                  </strong>
                </div>

                <div>
                  <small>TRANSFER</small>
                  <strong>
                    {candidate.transfers}회
                  </strong>
                </div>
              </div>

              <div className="candidate-score">
                {promoted && showComparison ? (
                  <>
                    <span>GENERAL 61 · MOBILITY 59</span>
                    <strong>3위 → 1위</strong>
                  </>
                ) : (
                  <>
                    <span>일반 적합도</span>
                    <strong>{candidate.score}</strong>
                  </>
                )}
              </div>

              {promoted && showComparison && (
                <motion.div
                  className="candidate-rank-shift"
                  initial={{
                    opacity: 0,
                    y: 8,
                  }}
                  animate={{
                    opacity: 1,
                    y: 0,
                  }}
                >
                  GENERAL 3위
                  <span>→</span>
                  MOBILITY 1위
                </motion.div>
              )}
            </motion.article>
          );
        })}
      </motion.div>

      <AnimatePresence>
        {showComparison && (
          <motion.section
            className="why-factor-stage"
            initial={{
              opacity: 0,
              x: 25,
            }}
            animate={{
              opacity: 1,
              x: 0,
            }}
            transition={{
              duration: 0.45,
              delay: 0.12,
            }}
          >
            <div className="factor-title">
              <small>WINNER COMPARISON</small>

              <h3>
                일반 1위와
                <br />
                이동지원 1위를 비교하면.
              </h3>
            </div>

            <div className="factor-grid">
              {evidence.map((item, index) => (
                <motion.div
                  key={item.en}
                  className="factor-card golden-factor"
                  initial={{
                    opacity: 0,
                    scale: 0.92,
                  }}
                  animate={{
                    opacity: 1,
                    scale: 1,
                  }}
                  transition={{
                    delay: 0.14 + index * 0.05,
                  }}
                >
                  <small>{item.en}</small>
                  <strong>{item.ko}</strong>

                  <b>{item.value}</b>

                  {item.delta && (
                    <em>{item.delta}</em>
                  )}

                  <span />
                </motion.div>
              ))}
            </div>
          </motion.section>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {showFinal && (
          <motion.section
            className="why-result golden-why-result"
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
            <small>DONGNET EXPLAINS THE RESULT</small>

            <h2>
              DongNet은
              <br />
              <em>나에게 더 맞는 길을 고릅니다.</em>
            </h2>

            <div className="why-reason">
              <span className="reason-dot" />

              <p>
                일반 3위였던 버스 77번이
                <strong> 이동지원 프로필에서는 1위로 상승했습니다.</strong>
              </p>
            </div>

            <p className="why-accessibility-summary">
              계단 회피 · 휠체어 경사 · 승강기 · 건물 진입 턱 조건도 함께 확인합니다.
            </p>

            <p className="golden-score-note">
              프로필마다 평가 기준이 달라지므로
              적합도 절대값보다
              <strong> 같은 후보군 안에서의 순위 변화</strong>를 봅니다.
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
