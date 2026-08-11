import { AnimatePresence, motion } from 'framer-motion';

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
  ['1,137', '실제 후보'],
  ['6,822', '프로필 평가'],
  ['304 / 76', 'Train / Valid OD'],
];

export function AIRankerScene({
  step,
}: AIRankerSceneProps) {
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
            className="ai-intro"
            initial={{ opacity: 0, y: 28 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -16 }}
            transition={{ duration: 0.7 }}
          >
            <p className="copy-kicker">
              AI APPLICATION
            </p>

            <h2>
              규칙으로 끝내지 않고,
              <br />
              <em>경로 선호를 학습하는 구조까지.</em>
            </h2>

            <p>
              동넷은 규칙 기반 서비스와
              <br />
              AI ranking 실험을 분리해 운영합니다.
            </p>
          </motion.section>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {step === 1 && (
          <motion.section
            className="ai-flow-stage"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <div className="ai-flow-heading">
              <small>PROFILE-SPECIFIC RANKING</small>
              <h2>
                같은 후보라도,
                <em> 프로필별 ranker는 다르게 봅니다.</em>
              </h2>
            </div>

            <div className="ai-flow">
              <article>
                <small>01 · INPUT</small>
                <strong>실제 후보 경로</strong>
                <span>A · B · C · D · E</span>
              </article>

              <i>→</i>

              <article>
                <small>02 · FEATURES</small>
                <strong>경로 피처</strong>
                <span>이동 · 접근성 · 환경</span>
              </article>

              <i>→</i>

              <article className="ai-model-card">
                <small>03 · MODEL</small>
                <strong>XGBoost Ranker</strong>

                <div className="ai-profile-row">
                  {profiles.map((profile) => (
                    <span key={profile}>
                      {profile}
                    </span>
                  ))}
                </div>
              </article>

              <i>→</i>

              <article className="ai-output-card">
                <small>04 · OUTPUT</small>
                <strong>후보군 순위</strong>
                <span>상대 적합도 비교</span>
              </article>
            </div>
          </motion.section>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {step === 2 && (
          <motion.section
            className="ai-baseline-stage"
            initial={{
              opacity: 0,
              y: 20,
            }}
            animate={{
              opacity: 1,
              y: 0,
            }}
            exit={{ opacity: 0 }}
          >
            <div className="ai-baseline-copy">
              <small>BOOTSTRAP TECHNICAL BASELINE</small>

              <h2>
                먼저,
                <br />
                <em>재현 가능한 baseline을 만들었습니다.</em>
              </h2>

              <p>
                동일 방향 OD는 train과 validation을
                넘나들지 않도록 분리합니다.
              </p>
            </div>

            <div className="ai-baseline-content">
              <div className="ai-metric-grid">
                {metrics.map(([value, label], index) => (
                  <motion.article
                    key={label}
                    initial={{
                      opacity: 0,
                      y: 18,
                    }}
                    animate={{
                      opacity: 1,
                      y: 0,
                    }}
                    transition={{
                      delay: index * 0.08,
                    }}
                  >
                    <strong>{value}</strong>
                    <span>{label}</span>
                  </motion.article>
                ))}
              </div>

              <div className="ai-evaluation-card">
                <small>RANKING QUALITY · TECHNICAL BASELINE</small>

                <div>
                  <span>NDCG@3</span>
                  <strong>0.9166 — 0.9596</strong>
                </div>

                <div>
                  <span>PAIRWISE ACCURACY</span>
                  <strong>0.6806 — 0.8315</strong>
                </div>

                <p>
                  ※ 고정 루브릭 기반 기술 baseline이며,
                  실제 사용자 효과를 의미하지 않습니다.
                </p>
              </div>
            </div>
          </motion.section>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {step === 3 && (
          <motion.section
            className="ai-gate-stage"
            initial={{
              opacity: 0,
              y: 22,
            }}
            animate={{
              opacity: 1,
              y: 0,
            }}
            exit={{ opacity: 0 }}
          >
            <div className="ai-gate-heading">
              <small>MODEL GOVERNANCE</small>

              <h2>
                모델을 만들었다고,
                <br />
                <em>바로 운영에 넣지는 않습니다.</em>
              </h2>
            </div>

            <div className="ai-gate-flow">
              <article>
                <small>TIER 01</small>
                <strong>BOOTSTRAP</strong>
                <span>기술 baseline</span>
                <b>운영 자동 승격 금지</b>
              </article>

              <i>→</i>

              <article>
                <small>TIER 02</small>
                <strong>HUMAN CANDIDATE</strong>
                <span>사람 라벨 기반 후보</span>
                <b>검토 필요</b>
              </article>

              <i>→</i>

              <article className="ai-approved">
                <small>TIER 03</small>
                <strong>HUMAN VALIDATED</strong>
                <span>근거 · 승인 검토</span>
                <b>운영 후보</b>
              </article>
            </div>

            <p className="ai-current-state">
              CURRENT SERVICE · LIVE MODE
              <strong> 규칙 기반 추천과 AI 실험 경로를 분리</strong>
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
