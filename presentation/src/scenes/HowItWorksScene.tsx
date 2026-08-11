import { AnimatePresence, motion } from 'framer-motion';

interface HowItWorksSceneProps {
  step: number;
}

const pipeline = [
  {
    no: '01',
    title: '이동 요청',
    en: 'REQUEST',
    desc: '출발지 · 목적지 · 사용자 프로필 · 이동 조건',
    chips: ['A → B', '프로필', '상황 조건'],
  },
  {
    no: '02',
    title: '후보 경로 수집',
    en: 'CANDIDATES',
    desc: '실제 대중교통·보행 경로 후보를 수집합니다.',
    chips: ['ODsay', 'TMAP', '보행 경로'],
  },
  {
    no: '03',
    title: '경로 데이터 결합',
    en: 'ENRICH',
    desc: '각 후보 경로 위에 이동 환경 데이터를 결합합니다.',
    chips: ['공간 레이어', '경사', '그늘', '날씨'],
  },
  {
    no: '04',
    title: '맞춤 적합도 계산',
    en: 'PERSONALIZE',
    desc: '사용자와 이동 조건에 따라 경로를 다르게 평가합니다.',
    chips: ['프로필', '가중치', '이동 조건'],
  },
  {
    no: '05',
    title: '추천',
    en: 'RANK',
    desc: '후보군을 적합도 순으로 비교하고 이유를 설명합니다.',
    chips: ['순위', '적합도', '추천 이유'],
  },
];

const dataSources = [
  ['9', '공간 레이어'],
  ['90m', '지형 경사'],
  ['LIVE', '날씨·대기'],
  ['시각별', '건물 그늘'],
];

export function HowItWorksScene({
  step,
}: HowItWorksSceneProps) {
  return (
    <main className="how-scene product-light">
      <div className="how-grid" />
      <div className="how-ambient" />

      <div className="presentation-hud">
        <span>05</span>
        <span className="hud-line" />
        <span>FROM REQUEST TO RECOMMENDATION</span>
      </div>

      <AnimatePresence mode="wait">
        {step === 0 && (
          <motion.section
            key="intro"
            className="how-intro"
            initial={{ opacity: 0, y: 28 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -18 }}
            transition={{ duration: 0.7 }}
          >
            <p className="copy-kicker">
              HOW DOES IT ACTUALLY WORK?
            </p>

            <h2>
              한 번의 검색 뒤에서는,
              <br />
              <em>이 과정이 움직입니다.</em>
            </h2>

            <p>
              동넷은 경로를 새로 만드는 것이 아니라,
              <br />
              실제 후보를 수집하고 이동 환경을 분석해 비교합니다.
            </p>
          </motion.section>
        )}
      </AnimatePresence>

      <motion.section
        className="pipeline-stage"
        initial={{ opacity: 0 }}
        animate={{ opacity: step >= 1 ? 1 : 0 }}
        transition={{ duration: 0.7 }}
      >
        <div className="pipeline-track">
          <motion.div
            className="pipeline-progress"
            initial={{ scaleX: 0 }}
            animate={{
              scaleX:
                step === 1
                  ? 0.2
                  : step === 1
                    ? 0.4
                    : step === 2
                      ? 0.6
                      : step === 2
                        ? 0.8
                        : step >= 3
                          ? 1
                          : 0,
            }}
            transition={{
              duration: 0.7,
              ease: [0.22, 1, 0.36, 1],
            }}
          />
        </div>

        <div className="pipeline-cards">
          {pipeline.map((item, index) => {
            const revealStep = [1, 1, 2, 2, 3][index] ?? 3;
            const visible = step >= revealStep;
            const active = step === revealStep;
            const complete = step > revealStep;

            return (
              <motion.article
                key={item.no}
                className={[
                  'pipeline-card',
                  active ? 'is-active' : '',
                  complete ? 'is-complete' : '',
                ].join(' ')}
                initial={{
                  opacity: 0,
                  y: 22,
                }}
                animate={{
                  opacity: visible ? 1 : 0.15,
                  y: visible ? 0 : 22,
                }}
                transition={{
                  duration: 0.55,
                  delay: visible ? 0.08 : 0,
                }}
              >
                <div className="pipeline-card-top">
                  <span>{item.no}</span>
                  <small>{item.en}</small>
                </div>

                <h3>{item.title}</h3>
                <p>{item.desc}</p>

                <div className="pipeline-chips">
                  {item.chips.map((chip) => (
                    <span key={chip}>{chip}</span>
                  ))}
                </div>
              </motion.article>
            );
          })}
        </div>
      </motion.section>

      <AnimatePresence>
        {step >= 2 && (
          <motion.aside
            className="how-data-proof"
            initial={{
              opacity: 0,
              x: 22,
            }}
            animate={{
              opacity: 1,
              x: 0,
            }}
            transition={{
              duration: 0.65,
            }}
          >
            <p>ROUTE CONTEXT</p>

            <div className="proof-stats">
              {dataSources.map(([value, label]) => (
                <div key={label}>
                  <strong>{value}</strong>
                  <span>{label}</span>
                </div>
              ))}
            </div>
          </motion.aside>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {step >= 3 && (
          <motion.div
            className="pipeline-result"
            initial={{
              opacity: 0,
              scale: 0.96,
            }}
            animate={{
              opacity: 1,
              scale: 1,
            }}
            transition={{
              duration: 0.7,
              ease: [0.22, 1, 0.36, 1],
            }}
          >
            <span className="result-mark" />

            <div>
              <small>DONGNET OUTPUT</small>
              <strong>
                “가장 빠른 길”이 아닌
                <em> “나에게 더 맞는 길”</em>
              </strong>
            </div>
          </motion.div>
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
