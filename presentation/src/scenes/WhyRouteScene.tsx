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
    value: '69분 → 77분',
  },
  {
    en: 'WALK',
    ko: '도보 거리',
    value: '1,252m → 1,068m',
    delta: '-184m',
  },
  {
    en: 'SLOPE',
    ko: '평균 경사',
    value: '6.82% → 6.55%',
    delta: '-0.27%p',
  },
  {
    en: 'SHADE',
    ko: '확인된 그늘',
    value: '5% → 12%',
    delta: '+7%p',
  },
  {
    en: 'TRANSFER',
    ko: '환승',
    value: '1회 → 1회',
  },
];

export function WhyRouteScene({
  step,
}: WhyRouteSceneProps) {
  return (
    <main className="why-scene product-light">
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
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -15 }}
            transition={{ duration: 0.7 }}
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

      <motion.div
        className="why-candidates"
        initial={{ opacity: 0 }}
        animate={{
          opacity: step >= 1 ? 1 : 0,
        }}
        transition={{ duration: 0.6 }}
      >
        {candidates.map((candidate, index) => {
          const promoted =
            candidate.id ===
            goldenDemo.comparison.promotedRoute;

          return (
            <motion.article
              key={candidate.id}
              className={`candidate-card ${
                index === 0 && step < 2
                  ? 'candidate-selected'
                  : ''
              } ${
                promoted && step >= 2
                  ? 'candidate-promoted'
                  : ''
              }`}
              initial={{
                opacity: 0,
                y: 25,
              }}
              animate={{
                opacity: step >= 1 ? 1 : 0,
                y: step >= 1 ? 0 : 25,

                scale:
                  step >= 2 && promoted
                    ? 1.025
                    : step >= 2
                      ? 0.94
                      : 1,
              }}
              transition={{
                duration: 0.6,
                delay: index * 0.1,
              }}
            >
              <div className="candidate-top">
                <small>ROUTE {candidate.id}</small>

                {step < 2 && index === 0 && (
                  <span>GENERAL 1위</span>
                )}

                {step >= 2 && promoted && (
                  <span>ELDERLY 1위</span>
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
                {promoted && step >= 2 ? (
                  <>
                    <span>GENERAL 51 · ELDERLY 36</span>
                    <strong>3위 → 1위</strong>
                  </>
                ) : (
                  <>
                    <span>일반 적합도</span>
                    <strong>{candidate.score}</strong>
                  </>
                )}
              </div>

              {promoted && step >= 2 && (
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
                  ELDERLY 1위
                </motion.div>
              )}
            </motion.article>
          );
        })}
      </motion.div>

      <AnimatePresence>
        {step >= 2 && (
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
              duration: 0.65,
            }}
          >
            <div className="factor-title">
              <small>WINNER COMPARISON</small>

              <h3>
                일반 1위와
                <br />
                고령자 1위를 비교하면.
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
                    delay: index * 0.07,
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
        {step >= 3 && (
          <motion.div
            className="why-weighting"
            initial={{
              opacity: 0,
              y: 22,
            }}
            animate={{
              opacity: 1,
              y: 0,
            }}
            transition={{ duration: 0.65 }}
          >
            <div>
              <small>ROUTE FEATURES</small>
              <strong>경로 특성</strong>
            </div>

            <span>×</span>

            <div className="weight-highlight">
              <small>USER CONTEXT</small>
              <strong>프로필 · 이동 조건</strong>
            </div>

            <span>→</span>

            <div>
              <small>RANKING</small>
              <strong>후보 순위 변화</strong>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {step >= 4 && (
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
              더 빠른 길이 아니라,
              <br />
              <em>나에게 더 맞는 길을 고릅니다.</em>
            </h2>

            <div className="why-reason">
              <span className="reason-dot" />

              <p>
                일반 3위였던 후보 C가
                <strong> 고령자 프로필에서는 1위로 상승했습니다.</strong>
              </p>
            </div>

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
