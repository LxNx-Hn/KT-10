import { AnimatePresence, motion } from 'framer-motion';

interface EndingSceneProps {
  step: number;
}

const routeA =
  'M 170 540 C 330 390, 440 430, 555 360 S 790 285, 930 350 S 1190 500, 1400 340';

const routeB =
  'M 170 540 C 310 610, 470 575, 610 495 S 850 410, 1015 455 S 1220 510, 1400 340';

export function EndingScene({
  step,
}: EndingSceneProps) {
  return (
    <main className="ending-scene">
      <div className="ending-grid" />
      <div className="ending-vignette" />

      <div className="presentation-hud">
        <span>13</span>
        <span className="hud-line" />
        <span>ONE DESTINATION</span>
      </div>

      <motion.div
        className="ending-map-stage"
        initial={{ opacity: 0 }}
        animate={{
          opacity: step >= 1 ? 1 : 0,
        }}
        transition={{ duration: 0.8 }}
      >
        <svg
          viewBox="0 0 1600 900"
          preserveAspectRatio="none"
        >
          <motion.path
            d={routeA}
            className="ending-route ending-route-a"
            initial={{ pathLength: 0 }}
            animate={{
              pathLength:
                step >= 1
                  ? 1
                  : 0,
            }}
            transition={{
              duration: 1.4,
              ease: [0.22, 1, 0.36, 1],
            }}
          />

          <motion.path
            d={routeB}
            className="ending-route ending-route-b"
            initial={{ pathLength: 0 }}
            animate={{
              pathLength:
                step >= 2
                  ? 1
                  : 0,
            }}
            transition={{
              duration: 1.4,
              ease: [0.22, 1, 0.36, 1],
            }}
          />
        </svg>

        <div className="ending-point ending-start">
          <span />
          <small>START</small>
        </div>

        <div className="ending-point ending-end">
          <span />
          <small>DESTINATION</small>
        </div>

        <AnimatePresence>
          {step === 2 && (
            <>
              <motion.div
                className="ending-persona persona-general"
                initial={{
                  opacity: 0,
                  y: 10,
                }}
                animate={{
                  opacity: 1,
                  y: 0,
                }}
              >
                <small>GENERAL</small>
                <strong>일반 사용자</strong>
              </motion.div>

              <motion.div
                className="ending-persona persona-access"
                initial={{
                  opacity: 0,
                  y: 10,
                }}
                animate={{
                  opacity: 1,
                  y: 0,
                }}
                transition={{ delay: 0.15 }}
              >
                <small>ACCESSIBILITY</small>
                <strong>이동지원 사용자</strong>
              </motion.div>
            </>
          )}
        </AnimatePresence>
      </motion.div>

      <AnimatePresence mode="wait">
        {step === 0 && (
          <motion.section
            key="ending-back"
            className="ending-opening-copy"
            initial={{
              opacity: 0,
              y: 25,
            }}
            animate={{
              opacity: 1,
              y: 0,
            }}
            exit={{
              opacity: 0,
            }}
            transition={{ duration: 0.7 }}
          >
            <p className="copy-kicker">
              BACK TO THE BEGINNING
            </p>

            <h2>
              다시,
              <br />
              처음의 질문으로.
            </h2>
          </motion.section>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {step >= 3 && (
          <motion.section
            className="ending-message"
            initial={{
              opacity: 0,
              scale: 0.96,
            }}
            animate={{
              opacity: 1,
              scale: 1,
            }}
            transition={{
              duration: 0.8,
              ease: [0.22, 1, 0.36, 1],
            }}
          >
            <p className="copy-kicker">
              DONGNET
            </p>

            <h2>
              목적지는 같아도,
              <br />
              <em>좋은 길의 기준은 다릅니다.</em>
            </h2>

            <motion.div
              className="ending-rule"
              initial={{
                scaleX: 0,
              }}
              animate={{
                scaleX: 1,
              }}
              transition={{
                delay: 0.4,
                duration: 0.8,
              }}
            />

            <p>
              동넷은 그 차이를
              <strong> 길에 반영합니다.</strong>
            </p>
          </motion.section>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {step >= 4 && (
          <motion.div
            className="ending-signoff"
            initial={{
              opacity: 0,
              y: 18,
            }}
            animate={{
              opacity: 1,
              y: 0,
            }}
            transition={{
              duration: 0.7,
            }}
          >
            <div className="ending-logo">
              <img
                className="brand-mark brand-mark-ending"
                src={`${import.meta.env.BASE_URL}brand/dongnet-app-icon.svg`}
                alt=""
                width={48}
                height={48}
              />
              <strong>DONGNET</strong>
            </div>

            <p>dongnet.kr</p>

            <div className="ending-qa">
              <small>THANK YOU</small>
              <strong>Q&A</strong>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </main>
  );
}
