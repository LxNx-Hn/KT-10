import { AnimatePresence, motion } from 'framer-motion';
import { stepSwap, useMotionVariants } from '../motion/stepSwap';

interface ExpansionSceneProps {
  step: number;
}

const roadmap = [
  {
    no: '01',
    kicker: 'NOW · PWA',
    title: '현재 · PWA 운영',
    body: '설치 가능한 웹앱으로 서비스 제공',
    tags: ['dongnet.kr', 'PWA', '프로필 추천'],
  },
  {
    no: '02',
    kicker: 'NEXT · PWA DEPTH',
    title: '다음 · PWA 고도화',
    body: '접근성·성능·사용성 개선',
    tags: ['접근성', '성능', '사용성'],
  },
  {
    no: '03',
    kicker: 'NEXT · SCALE',
    title: '확장 · 지역·공공 연계',
    body: '지역 데이터와 공공 이동 서비스 연결',
    tags: ['지역 데이터', '추천 API', '공공 이동'],
  },
];

const loop = [
  ['01', 'PWA 실제 이용', '경로 추천'],
  ['02', '사용자 피드백', '후기 · 오류 신고'],
  ['03', '품질 지표 확인', '추천 품질'],
  ['04', '추천 개선', '프로필별 경로 평가'],
];

const nextMetrics = [
  ['01', 'PWA 이용 지속률', '설치 가능한 웹앱을 얼마나 이어 쓰는가'],
  ['02', '프로필별 만족도', '사용자 조건에 맞는 이동 경험'],
  ['03', '추천 품질', '프로필별 경로 평가와 재정렬'],
  ['04', '지역 적용성', '다른 지역에서도 동일 구조가 유효한가'],
];

export function ExpansionScene({
  step,
}: ExpansionSceneProps) {
  const motionVars = useMotionVariants();

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
            key="expansion-intro"
            className="expansion-intro"
            {...stepSwap}
          >
            <motion.p
              className="copy-kicker"
              variants={motionVars.fadeIn}
              initial="hidden"
              animate="show"
            >
              SERVICE EXPANSION
            </motion.p>

            <h2>
              <motion.span variants={motionVars.softRise} initial="hidden" animate="show">
                하나의 PWA로,
              </motion.span>
              <motion.span variants={motionVars.softRise} initial="hidden" animate="show">
                <em>모바일 이동 경험을 확장합니다.</em>
              </motion.span>
            </h2>

            <motion.p
              variants={motionVars.fadeIn}
              initial="hidden"
              animate="show"
            >
              프로필별 경로 평가와 추천을
              <br />
              설치 가능한 웹앱으로 운영합니다.
            </motion.p>
          </motion.section>
        )}

        {step === 1 && (
          <motion.section
            key="expansion-roadmap"
            className="expansion-roadmap"
            {...stepSwap}
          >
            <motion.div
              className="expansion-heading"
              variants={motionVars.softRise}
              initial="hidden"
              animate="show"
            >
              <small>EXPANSION ROADMAP</small>
              <h2>
                <span>하나의 PWA로,</span>
                <span>
                  <em>모바일 이동 경험을 확장합니다.</em>
                </span>
              </h2>
            </motion.div>

            <motion.div
              className="expansion-cards"
              variants={motionVars.staggerContainer}
              initial="hidden"
              animate="show"
            >
              {roadmap.flatMap((card, index) => {
                const article = (
                  <motion.article
                    key={card.no}
                    className={index === 0 ? 'expansion-now' : undefined}
                    variants={motionVars.softScale}
                  >
                    <div className="expansion-number">{card.no}</div>
                    <small>{card.kicker}</small>
                    <h3>{card.title}</h3>
                    <p>{card.body}</p>
                    <div>
                      {card.tags.map((tag) => (
                        <span key={tag}>{tag}</span>
                      ))}
                    </div>
                  </motion.article>
                );

                if (index === 0) {
                  return [article];
                }

                return [
                  <motion.i
                    key={`arrow-${card.no}`}
                    className="motion-arrow"
                    variants={motionVars.drawLine}
                  >
                    →
                  </motion.i>,
                  article,
                ];
              })}
            </motion.div>
          </motion.section>
        )}

        {step === 2 && (
          <motion.section
            key="expansion-loop"
            className="expansion-loop"
            {...stepSwap}
          >
            <motion.div
              className="expansion-loop-copy"
              variants={motionVars.softRise}
              initial="hidden"
              animate="show"
            >
              <small>PWA QUALITY LOOP</small>

              <h2>
                이용이 쌓이면,
                <br />
                <em>검증도 쌓입니다.</em>
              </h2>

              <p>
                PWA 실제 이용 → 사용자 피드백 → 품질 지표 확인 → 추천 개선
              </p>
            </motion.div>

            <motion.div
              className="feedback-loop-diagram"
              variants={motionVars.staggerContainer}
              initial="hidden"
              animate="show"
            >
              {loop.flatMap(([no, title, detail], index) => {
                const article = (
                  <motion.article
                    key={title}
                    className={index === 3 ? 'loop-accent' : undefined}
                    variants={motionVars.softScale}
                  >
                    <small>{no}</small>
                    <strong>{title}</strong>
                    <span>{detail}</span>
                  </motion.article>
                );

                if (index === 0) {
                  return [article];
                }

                return [
                  <motion.i
                    key={`loop-arrow-${title}`}
                    className="motion-arrow"
                    variants={motionVars.drawLine}
                  >
                    →
                  </motion.i>,
                  article,
                ];
              })}
            </motion.div>
          </motion.section>
        )}

        {step === 3 && (
          <motion.section
            key="expansion-impact"
            className="expansion-impact"
            {...stepSwap}
          >
            <motion.div
              className="expansion-impact-title"
              variants={motionVars.softRise}
              initial="hidden"
              animate="show"
            >
              <small>EFFECTIVENESS · NEXT METRICS</small>

              <h2>
                <span>PWA 운영 이후,</span>
                <span>
                  <em>실제 이동 경험의 변화로 검증합니다.</em>
                </span>
              </h2>
            </motion.div>

            <motion.div
              className="impact-metric-grid"
              variants={motionVars.staggerContainer}
              initial="hidden"
              animate="show"
            >
              {nextMetrics.map(([no, title, detail]) => (
                <motion.article
                  key={title}
                  variants={motionVars.softScale}
                >
                  <small>{no}</small>
                  <strong>{title}</strong>
                  <span>{detail}</span>
                </motion.article>
              ))}
            </motion.div>

            <motion.p
              className="future-label"
              variants={motionVars.fadeIn}
              initial="hidden"
              animate="show"
            >
              ※ 위 항목은 향후 서비스 효과 검증 지표입니다.
            </motion.p>
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
