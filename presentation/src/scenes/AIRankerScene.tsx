import { AnimatePresence, motion } from 'framer-motion';
import { stepSwap, useMotionVariants } from '../motion/stepSwap';

interface AIRankerSceneProps {
  step: number;
}

const profiles = [
  'GENERAL',
  'ELDERLY',
  'CHILD',
  'YOUTH',
  'MOBILITY',
  'PREGNANT',
];

const metrics = [
  ['380', 'OD'],
  ['1,137', '실제 후보 경로'],
  ['6,822', '평가 라벨'],
  ['304 / 76', 'Train / Valid OD'],
];

const validationEase = [0.22, 1, 0.36, 1] as const;

const validationStagger = {
  hidden: {},
  show: {
    transition: {
      delayChildren: 0.02,
      staggerChildren: 0.05,
    },
  },
};

const validationItem = {
  hidden: { opacity: 0, y: 10 },
  show: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.28,
      ease: validationEase,
    },
  },
};

const learnFlow = [
  {
    no: '01',
    title: 'KT 믿음 K 2.0',
    detail: '프로필별 평가 항목 정리',
  },
  {
    no: '02',
    title: '평가 라벨 생성',
    detail: '실제 후보 경로 6,822건',
  },
  {
    no: '03',
    title: 'XGBoost Ranker',
    detail: '프로필별 경로 순위 학습',
  },
];

export function AIRankerScene({
  step,
}: AIRankerSceneProps) {
  const motionVars = useMotionVariants();

  return (
    <main className="ai-scene product-light">
      <div className="ai-grid" />
      <div className="ai-blue-glow" />
      <div className="ai-green-glow" />

      <div className="presentation-hud">
        <span>09</span>
        <span className="hud-line" />
        <span>AI RANKING & VALIDATION</span>
      </div>

      <AnimatePresence mode="wait">
        {step === 0 && (
          <motion.section
            key="ai-intro"
            className="ai-intro"
            {...stepSwap}
          >
            <motion.p
              className="copy-kicker"
              variants={motionVars.fadeIn}
              initial="hidden"
              animate="show"
            >
              AI APPLICATION
            </motion.p>

            <h2>
              <motion.span variants={motionVars.softRise} initial="hidden" animate="show">
                실제 후보 경로로
              </motion.span>
              <br />
              <motion.span variants={motionVars.softRise} initial="hidden" animate="show">
                <em>프로필별 순위 모델을 학습했습니다.</em>
              </motion.span>
            </h2>

            <motion.p
              variants={motionVars.fadeIn}
              initial="hidden"
              animate="show"
            >
              380개 OD에서 1,137개 후보 경로를 만들고,
              <br />
              6,822개 평가 라벨로 XGBoost Ranker를 학습했습니다.
            </motion.p>
          </motion.section>
        )}

        {step === 1 && (
          <motion.section
            key="ai-flow"
            className="ai-flow-stage"
            {...stepSwap}
          >
            <motion.div
              className="ai-flow-heading"
              variants={motionVars.softRise}
              initial="hidden"
              animate="show"
            >
              <small>PROFILE-SPECIFIC RANKING</small>
              <h2>
                프로필별 평가 라벨을 만들고,
                <br />
                <em>XGBoost로 후보 순위를 학습했습니다.</em>
              </h2>
            </motion.div>

            <motion.div
              className="ai-flow ai-flow-extended"
              variants={motionVars.staggerContainer}
              initial="hidden"
              animate="show"
            >
              {learnFlow.map((item) => (
                <motion.article
                  key={item.no}
                  className={
                    item.no === '01'
                      ? 'ai-model-card'
                      : item.no === '03'
                        ? 'ai-output-card'
                        : undefined
                  }
                  variants={motionVars.softScale}
                >
                  <small>{item.no}</small>
                  <strong>{item.title}</strong>
                  <span>{item.detail}</span>
                </motion.article>
              ))}
            </motion.div>

            <motion.p
              className="ai-flow-note"
              variants={motionVars.fadeIn}
              initial="hidden"
              animate="show"
            >
                같은 후보 경로를 여섯 프로필에 맞춰 각각 평가했습니다.
                <span>
                  {profiles.join(' · ')}
                </span>
              </motion.p>
          </motion.section>
        )}

        {step === 2 && (
          <motion.section
            key="ai-baseline"
            className="ai-baseline-stage"
            {...stepSwap}
          >
            <motion.div
              className="ai-baseline-copy"
              variants={validationItem}
              initial="hidden"
              animate="show"
            >
              <small>KT 믿음 K 2.0</small>

              <h2>
                380개 OD에서
                <br />
                <em>1,137개 후보 경로를 학습했습니다.</em>
              </h2>

              <p>
                304개 OD는 학습에, 76개 OD는 검증에 사용했습니다.
                프로필별 순위가 얼마나 맞는지 NDCG@3와
                pairwise accuracy로 확인했습니다.
              </p>
            </motion.div>

            <motion.div
              className="ai-baseline-content"
              variants={validationStagger}
              initial="hidden"
              animate="show"
            >
              <motion.div
                className="ai-metric-grid"
                variants={validationItem}
              >
                {metrics.map(([value, label]) => (
                  <article key={label}>
                    <strong>{value}</strong>
                    <span>{label}</span>
                  </article>
                ))}
              </motion.div>

              <motion.div
                className="ai-evaluation-card"
                variants={validationItem}
              >
                <small>RANKING QUALITY · XGBoost Ranker</small>

                <div>
                  <span>NDCG@3</span>
                  <strong>0.9166 — 0.9596</strong>
                </div>

                <div>
                  <span>PAIRWISE ACCURACY</span>
                  <strong>0.6806 — 0.8315</strong>
                </div>

                <p>
                  ※ KT 믿음 K 2.0으로 프로필별 평가 라벨을 만들었으며,
                  <br />
                  위 수치는 XGBoost Ranker의 검증 결과입니다.
                </p>
              </motion.div>
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
