import { AnimatePresence, motion } from 'framer-motion';
import { stepSwap, useMotionVariants } from '../motion/stepSwap';

interface ScoringSceneProps {
  step: number;
}

const groups = [
  {
    title: '이동 부담',
    en: 'MOVEMENT',
    items: ['시간 효율', '보행 편의', '경사도', '환승 단순성'],
  },
  {
    title: '접근성',
    en: 'ACCESSIBILITY',
    items: ['접근성', '승강기', '저상버스', '계단', '단차'],
  },
  {
    title: '환경 · 상태',
    en: 'CONTEXT',
    items: ['그늘', '폭염 · 날씨', '안전', '데이터 신뢰도'],
  },
];

const profiles = [
  '일반',
  '고령자',
  '아동',
  '청년',
  '이동지원',
  '임산부',
];

export function ScoringScene({
  step,
}: ScoringSceneProps) {
  const motionVars = useMotionVariants();

  return (
    <main className="score-scene product-light">
      <div className="score-grid-bg" />
      <div className="score-ambient score-ambient-a" />
      <div className="score-ambient score-ambient-b" />

      <div className="presentation-hud">
        <span>08</span>
        <span className="hud-line" />
        <span>FROM FEATURES TO SCORE</span>
      </div>

      <AnimatePresence mode="wait">
        {step === 0 && (
          <motion.section
            key="score-intro"
            className="score-intro"
            {...stepSwap}
          >
            <motion.p
              className="copy-kicker"
              variants={motionVars.fadeIn}
              initial="hidden"
              animate="show"
            >
              PERSONALIZED SCORING
            </motion.p>

            <h2>
              <motion.span variants={motionVars.softRise} initial="hidden" animate="show">
                프로필마다 같은 피처의
              </motion.span>
              <br />
              <motion.span variants={motionVars.softRise} initial="hidden" animate="show">
                <em>중요도가 달라집니다.</em>
              </motion.span>
            </h2>
          </motion.section>
        )}

        {step === 1 && (
          <motion.section
            key="score-groups"
            className="score-components-stage"
            {...stepSwap}
          >
            <motion.div
              className="score-groups score-groups-large"
              variants={motionVars.staggerContainer}
              initial="hidden"
              animate="show"
            >
              {groups.map((group) => (
                <motion.article
                  key={group.title}
                  className="score-group"
                  variants={motionVars.softScale}
                >
                  <div className="score-group-title">
                    <small>{group.en}</small>
                    <h3>{group.title}</h3>
                  </div>

                  <div className="score-component-list">
                    {group.items.map((item, index) => (
                      <div key={item} className="score-component">
                        <span className="component-index">
                          {String(index + 1).padStart(2, '0')}
                        </span>
                        <strong>{item}</strong>
                      </div>
                    ))}
                  </div>
                </motion.article>
              ))}
            </motion.div>
          </motion.section>
        )}

        {step === 2 && (
          <motion.section
            key="score-profiles"
            className="score-profile-stage"
            {...stepSwap}
          >
            <motion.div
              className="score-profile-copy"
              variants={motionVars.staggerContainer}
              initial="hidden"
              animate="show"
            >
              <motion.small variants={motionVars.fadeIn}>
                PROFILE SCORING
              </motion.small>
              <h2>
                경로 피처에서
                <br />
                <em>프로필별 경로 적합 지수로.</em>
              </h2>
              <p>
                경로 피처 → 프로필별 평가 기준 → 0–100점 → 프로필별 경로 적합 지수
              </p>
            </motion.div>

            <motion.div
              className="score-profile-grid"
              variants={motionVars.staggerContainer}
              initial="hidden"
              animate="show"
            >
              {profiles.map((item) => (
                <motion.article
                  key={item}
                  className={
                    item === '이동지원' ? 'is-mobility' : undefined
                  }
                  variants={motionVars.softScale}
                >
                  <strong>{item}</strong>
                  {item === '이동지원' ? (
                    <span>휠체어 이동 조건 포함</span>
                  ) : null}
                </motion.article>
              ))}
            </motion.div>
          </motion.section>
        )}

        {step >= 3 && (
          <motion.section
            key="score-final"
            className="score-final-message"
            {...stepSwap}
          >
            <motion.p
              variants={motionVars.fadeIn}
              initial="hidden"
              animate="show"
            >
              DONGNET SCORE
            </motion.p>

            <h2>
              <motion.span variants={motionVars.softRise} initial="hidden" animate="show">
                DongNet이 계산한
              </motion.span>
              <br />
              <motion.span variants={motionVars.softScale} initial="hidden" animate="show">
                <em>프로필별 경로 적합 지수입니다.</em>
              </motion.span>
            </h2>
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
