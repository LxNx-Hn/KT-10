import { AnimatePresence, motion } from 'framer-motion';

interface ExpansionSceneProps {
  step: number;
}

export function ExpansionScene({
  step,
}: ExpansionSceneProps) {
  return (
    <main className="expansion-scene product-light">
      <div className="expansion-grid" />
      <div className="expansion-glow-a" />
      <div className="expansion-glow-b" />

      <div className="presentation-hud">
        <span>12</span>
        <span className="hud-line" />
        <span>FROM SERVICE TO PUBLIC VALUE</span>
      </div>

      <AnimatePresence mode="wait">
        {step === 0 && (
          <motion.section
            className="expansion-intro"
            initial={{ opacity: 0, y: 28 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -16 }}
            transition={{ duration: 0.7 }}
          >
            <p className="copy-kicker">
              SERVICE EXPANSION
            </p>

            <h2>
              부산에서 시작해,
              <br />
              <em>더 넓은 이동 문제로 확장합니다.</em>
            </h2>

            <p>
              현재 서비스와 향후 확장 전략을
              <br />
              단계적으로 설계했습니다.
            </p>
          </motion.section>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {step === 1 && (
          <motion.section
            className="expansion-roadmap"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <div className="expansion-heading">
              <small>EXPANSION ROADMAP</small>
              <h2>
                하나의 경로 서비스에서,
                <em> 이동 접근성 인프라로.</em>
              </h2>
            </div>

            <div className="expansion-cards">
              <article className="expansion-now">
                <div className="expansion-number">01</div>
                <small>NOW · BUSAN</small>
                <h3>실제 서비스</h3>

                <p>
                  사용자 프로필과 이동 조건에 따른
                  부산 맞춤 경로 추천
                </p>

                <div>
                  <span>dongnet.kr</span>
                  <span>추천 이유</span>
                  <span>후기 · 시설 신고</span>
                </div>
              </article>

              <i>→</i>

              <article>
                <div className="expansion-number">02</div>
                <small>NEXT · REGION</small>
                <h3>지역 확장</h3>

                <p>
                  지역별 교통·접근성·환경 데이터를
                  동일한 평가 구조에 연결
                </p>

                <div>
                  <span>지역 데이터</span>
                  <span>공간 레이어</span>
                  <span>공통 scoring contract</span>
                </div>
              </article>

              <i>→</i>

              <article>
                <div className="expansion-number">03</div>
                <small>NEXT · PUBLIC MOBILITY</small>
                <h3>공공 이동 서비스 연계</h3>

                <p>
                  지자체 이동지원·교통복지 서비스에서
                  활용 가능한 추천 구조로 확장
                </p>

                <div>
                  <span>추천 API</span>
                  <span>이동지원</span>
                  <span>정책 연계안</span>
                </div>
              </article>
            </div>
          </motion.section>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {step === 2 && (
          <motion.section
            className="expansion-loop"
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
            <div className="expansion-loop-copy">
              <small>HUMAN FEEDBACK LOOP</small>

              <h2>
                서비스가 쓰일수록,
                <br />
                <em>검증 가능한 피드백도 쌓이도록.</em>
              </h2>

              <p>
                사용자 동의와 검토를 거친 피드백은
                향후 모델 검증 데이터로 활용할 수 있습니다.
              </p>
            </div>

            <div className="feedback-loop-diagram">
              <article>
                <small>01</small>
                <strong>실제 이용</strong>
                <span>경로 추천</span>
              </article>

              <i>→</i>

              <article>
                <small>02</small>
                <strong>사용자 피드백</strong>
                <span>후기 · 오류 신고</span>
              </article>

              <i>→</i>

              <article>
                <small>03</small>
                <strong>Human Validation</strong>
                <span>근거 검토</span>
              </article>

              <i>→</i>

              <article className="loop-accent">
                <small>04</small>
                <strong>추천 개선</strong>
                <span>차기 모델 후보</span>
              </article>
            </div>
          </motion.section>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {step === 3 && (
          <motion.section
            className="expansion-impact"
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
            <div className="expansion-impact-title">
              <small>EFFECTIVENESS · NEXT METRICS</small>

              <h2>
                확장은 기능 수가 아니라,
                <br />
                <em>실제 이동 경험의 변화로 검증합니다.</em>
              </h2>
            </div>

            <div className="impact-metric-grid">
              <article>
                <small>01</small>
                <strong>추천 선택</strong>
                <span>어떤 추천이 실제로 선택되는가</span>
              </article>

              <article>
                <small>02</small>
                <strong>이동 만족도</strong>
                <span>프로필별 체감 이동 부담 변화</span>
              </article>

              <article>
                <small>03</small>
                <strong>데이터 개선</strong>
                <span>시설 오류·접근성 신고 반영</span>
              </article>

              <article>
                <small>04</small>
                <strong>지역 적용성</strong>
                <span>다른 지역에서도 동일 구조가 유효한가</span>
              </article>
            </div>

            <p className="future-label">
              ※ 위 항목은 향후 서비스 효과 검증 지표입니다.
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
