import { AnimatePresence, motion } from 'framer-motion';
import { presentationData } from '../data/presentationData';
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

const learnFlow = [
  {
    no: '01',
    title: 'KT 믿음 K 2.0',
    detail: '프로필별 평가 기준',
  },
  {
    no: '02',
    title: '판단 근거 · 평가 라벨',
    detail: '프로필별 라벨 구성',
  },
  {
    no: '03',
    title: 'XGBoost Ranker',
    detail: '경로 순위 학습',
  },
  {
    no: '04',
    title: 'NDCG@3 · Pairwise',
    detail: '순위 품질 검증',
  },
  {
    no: '05',
    title: 'PWA 추천 연결',
    detail: '실제 추천 경험',
  },
];

const pwaOutputs = [
  {
    title: '프로필별 경로 점수',
    detail: '0–100점',
  },
  {
    title: 'AI Ranker 재정렬',
    detail: '후보 우선순위',
  },
  {
    title: '추천 이유 제공',
    detail: '사용자 설명',
  },
];

export function AIRankerScene({
  step,
}: AIRankerSceneProps) {
  const { evaluationStandard } = presentationData;
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
                실제 후보 경로를
              </motion.span>
              <br />
              <motion.span variants={motionVars.softRise} initial="hidden" animate="show">
                <em>순위 모델 학습으로 검증했습니다.</em>
              </motion.span>
            </h2>

            <motion.p
              variants={motionVars.fadeIn}
              initial="hidden"
              animate="show"
            >
              {`${evaluationStandard}이 프로필별 판단 근거를 정의하고,`}
              <br />
              XGBoost Ranker가 경로의 순서를 학습합니다.
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
                평가 기준은 판단 근거를 정의하고,
                {' '}
                <em>Ranker는 순서를 학습합니다.</em>
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
                평가 기준은 프로필별 판단 근거를 정의하고, Ranker는 경로의 순서를 학습합니다.
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
              variants={motionVars.staggerContainer}
              initial="hidden"
              animate="show"
            >
              <motion.small variants={motionVars.fadeIn}>
                KT 믿음 K 2.0
              </motion.small>

              <h2>
                KT 믿음 K 2.0
                <br />
                <em>기반 프로필 평가 기준</em>
              </h2>

              <p>
                평가 기준은 프로필별 판단 근거를 정의하고,
                Ranker는 경로의 순서를 학습합니다.
                동일 방향 OD는 Train 304 / Valid 76으로 분리합니다.
              </p>
            </motion.div>

            <motion.div
              className="ai-baseline-content"
              variants={motionVars.staggerContainer}
              initial="hidden"
              animate="show"
            >
              <motion.div
                className="ai-metric-grid"
                variants={motionVars.staggerContainer}
              >
                {metrics.map(([value, label]) => (
                  <motion.article
                    key={label}
                    variants={motionVars.numberReveal}
                  >
                    <strong>{value}</strong>
                    <span>{label}</span>
                  </motion.article>
                ))}
              </motion.div>

              <motion.div
                className="ai-evaluation-card"
                variants={motionVars.softScale}
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
                  ※ KT 믿음 K 2.0은 프로필별 평가 기준이며,
                  위 수치는 XGBoost Ranker 검증 결과입니다.
                </p>
              </motion.div>
            </motion.div>
          </motion.section>
        )}

        {step === 3 && (
          <motion.section
            key="ai-pwa"
            className="ai-gate-stage"
            {...stepSwap}
          >
            <motion.div
              className="ai-gate-heading"
              variants={motionVars.softRise}
              initial="hidden"
              animate="show"
            >
              <small>FROM MODEL TO PWA</small>

              <h2>
                <span>검증된 모델 출력을</span>
                <span>
                  <em>PWA 추천 경험에 연결했습니다.</em>
                </span>
              </h2>
            </motion.div>

            <motion.div
              className="ai-gate-flow"
              variants={motionVars.staggerContainer}
              initial="hidden"
              animate="show"
            >
              {pwaOutputs.map((item) => (
                <motion.article
                  key={item.title}
                  variants={motionVars.softScale}
                >
                  <strong>{item.title}</strong>
                  <span>{item.detail}</span>
                </motion.article>
              ))}
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
