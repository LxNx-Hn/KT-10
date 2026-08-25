import { AnimatePresence, motion } from 'framer-motion';
import { presentationData } from '../data/presentationData';
import { ProblemPrologueScene } from './ProblemPrologueScene';

interface OpeningSceneProps {
  step: number;
}

const routePath =
  'M 190 590 C 280 515, 330 545, 410 465 S 565 360, 665 405 S 815 500, 905 388 S 1040 245, 1165 285 S 1320 420, 1440 330';

const alternatePath =
  'M 190 590 C 285 625, 385 600, 460 545 S 610 495, 705 520 S 870 555, 960 485 S 1110 395, 1165 285';

export function OpeningScene({ step }: OpeningSceneProps) {
  const { origin, destination } = presentationData.demo;

  if (step === 1) {
    return <ProblemPrologueScene />;
  }

  return (
    <main className="opening-scene">
      <div className="opening-vignette" />

      <motion.div
        className="map-stage"
        initial={{ opacity: 0, scale: 1.025 }}
        animate={{
          opacity: step >= 2 ? 1 : 0,
          scale: step >= 2 ? 1 : 1.025,
        }}
        transition={{ duration: 1.25, ease: [0.22, 1, 0.36, 1] }}
      >
        <div className="map-grid" />

        <div className="water-shape water-shape-a" />
        <div className="water-shape water-shape-b" />

        <div className="map-road road-1" />
        <div className="map-road road-2" />
        <div className="map-road road-3" />
        <div className="map-road road-4" />
        <div className="map-road road-5" />

        <span className="district district-1">BUSAN</span>
        <span className="district district-2">DONG-GU</span>
        <span className="district district-3">BUSANJIN-GU</span>

        <svg
          className="route-layer"
          viewBox="0 0 1600 900"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <defs>
            <filter id="routeGlow" x="-40%" y="-40%" width="180%" height="180%">
              <feGaussianBlur stdDeviation="7" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          <motion.path
            d={alternatePath}
            className="route-alternate"
            initial={{ pathLength: 0, opacity: 0 }}
            animate={{
              pathLength: step >= 5 ? 1 : 0,
              opacity: step >= 5 ? 0.28 : 0,
            }}
            transition={{ duration: 1.2, ease: 'easeInOut' }}
          />

          <motion.path
            d={routePath}
            className="route-main-glow"
            initial={{ pathLength: 0 }}
            animate={{ pathLength: step >= 3 ? 1 : 0 }}
            transition={{
              duration: 1.65,
              ease: [0.65, 0, 0.35, 1],
            }}
            filter="url(#routeGlow)"
          />

          <motion.path
            d={routePath}
            className="route-main"
            initial={{ pathLength: 0 }}
            animate={{ pathLength: step >= 3 ? 1 : 0 }}
            transition={{
              duration: 1.65,
              ease: [0.65, 0, 0.35, 1],
            }}
          />
        </svg>

        <motion.div
          className="route-point route-point-origin"
          initial={{ scale: 0, opacity: 0 }}
          animate={{
            scale: step >= 3 ? 1 : 0,
            opacity: step >= 3 ? 1 : 0,
          }}
          transition={{ type: 'spring', stiffness: 220, damping: 18 }}
        >
          <span className="point-core" />
          <div className="point-label">
            <small>START</small>
            <strong>{origin}</strong>
          </div>
        </motion.div>

        <motion.div
          className="route-point route-point-destination"
          initial={{ scale: 0, opacity: 0 }}
          animate={{
            scale: step >= 3 ? 1 : 0,
            opacity: step >= 3 ? 1 : 0,
          }}
          transition={{
            type: 'spring',
            stiffness: 220,
            damping: 18,
            delay: step >= 3 ? 1.25 : 0,
          }}
        >
          <span className="point-core destination-core" />
          <div className="point-label destination-label">
            <small>DESTINATION</small>
            <strong>{destination}</strong>
          </div>
        </motion.div>
      </motion.div>

      <AnimatePresence mode="wait">
        {step === 0 && (
          <motion.section
            key="intro"
            className="opening-copy opening-copy-center"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: 0.7 }}
          >
            <p className="eyebrow">KT AI 기반 사회문제해결 프로젝트 · TEAM 10</p>

            <h1 className="opening-logo">
              <img
                className="brand-mark brand-mark-opening"
                src={`${import.meta.env.BASE_URL}brand/dongnet-app-icon.svg`}
                alt=""
                width={56}
                height={56}
              />
              DONGNET
            </h1>

            <p className="opening-korean">동넷</p>
          </motion.section>
        )}

        {step === 4 && (
          <motion.section
            key="fastest"
            className="opening-copy route-question-copy"
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -16 }}
            transition={{ duration: 0.65 }}
          >
            <p className="copy-kicker">ROUTE FOUND</p>
            <h2>
              가장 빠른 길은
              <br />
              찾을 수 있습니다.
            </h2>
          </motion.section>
        )}

        {step === 5 && (
          <motion.section
            key="but"
            className="opening-copy route-question-copy"
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -16 }}
            transition={{ duration: 0.65 }}
          >
            <p className="copy-kicker">BUT</p>
            <h2>
              누구에게나
              <br />
              같은 길이 좋은 길일까요?
            </h2>
          </motion.section>
        )}

        {step === 6 && (
          <motion.section
            key="question"
            className="opening-copy opening-final-question"
            initial={{ opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
          >
            <p className="copy-kicker">THE QUESTION</p>

            <h2>
              목적지는 같아도,
              <br />
              <em>좋은 길의 기준</em>은 다릅니다.
            </h2>

            <motion.div
              className="question-rule"
              initial={{ scaleX: 0 }}
              animate={{ scaleX: 1 }}
              transition={{ delay: 0.45, duration: 0.8 }}
            />

            <p className="question-sub">
              이동하는 사람을 이해하는 길찾기.
            </p>
          </motion.section>
        )}
      </AnimatePresence>

      <motion.div
        className="presentation-hud"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1 }}
      >
        <span>01</span>
        <span className="hud-line" />
        <span>OPENING</span>
      </motion.div>

      <div className="presentation-help">
        <span>SPACE</span>
        <span>진행</span>
        <span className="help-divider">·</span>
        <span>←</span>
        <span>이전</span>
        <span className="help-divider">·</span>
        <span>F</span>
        <span>전체화면</span>
      </div>
    </main>
  );
}
