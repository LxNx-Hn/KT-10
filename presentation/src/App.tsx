import { AnimatePresence, motion } from 'framer-motion';

import { OpeningScene } from './scenes/OpeningScene';
import { ProblemScene } from './scenes/ProblemScene';
import { ProblemDefinitionScene } from './scenes/ProblemDefinitionScene';
import { DongNetRevealScene } from './scenes/DongNetRevealScene';
import { HowItWorksScene } from './scenes/HowItWorksScene';
import { LiveDemoScene } from './scenes/LiveDemoScene';
import { WhyRouteScene } from './scenes/WhyRouteScene';
import { ScoringScene } from './scenes/ScoringScene';
import { AIRankerScene } from './scenes/AIRankerScene';
import { DifferenceScene } from './scenes/DifferenceScene';
import { BuiltScene } from './scenes/BuiltScene';
import { ExpansionScene } from './scenes/ExpansionScene';
import { EndingScene } from './scenes/EndingScene';

import { usePresentation } from './hooks/usePresentation';

import './presentation.css';

function App() {
  const presentation = usePresentation();

  const sceneContent = () => {
    switch (presentation.scene) {
      case 0:
        return <OpeningScene step={presentation.step} />;

      case 1:
        return <ProblemScene step={presentation.step} />;

      case 2:
        return (
          <ProblemDefinitionScene
            step={presentation.step}
          />
        );

      case 3:
        return (
          <DongNetRevealScene
            step={presentation.step}
          />
        );

      case 4:
        return (
          <HowItWorksScene
            step={presentation.step}
          />
        );

      case 5:
        return (
          <LiveDemoScene
            step={presentation.step}
          />
        );

      case 6:
        return (
          <WhyRouteScene
            step={presentation.step}
          />
        );

      case 7:
        return (
          <ScoringScene
            step={presentation.step}
          />
        );

      case 8:
        return (
          <AIRankerScene
            step={presentation.step}
          />
        );

      case 9:
        return (
          <DifferenceScene
            step={presentation.step}
          />
        );

      case 10:
        return (
          <BuiltScene
            step={presentation.step}
          />
        );

      case 11:
        return (
          <ExpansionScene
            step={presentation.step}
          />
        );

      case 12:
        return (
          <EndingScene
            step={presentation.step}
          />
        );

      default:
        return null;
    }
  };

  return (
    <div className="presentation-shell">
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={`scene-${presentation.scene}`}
          className="scene-frame"
          initial={{
            opacity: 0,
            scale: 0.985,
            filter: 'blur(5px)',
          }}
          animate={{
            opacity: 1,
            scale: 1,
            filter: 'blur(0px)',
          }}
          exit={{
            opacity: 0,
            scale: 1.012,
            filter: 'blur(5px)',
          }}
          transition={{
            duration: 0.68,
            ease: [0.22, 1, 0.36, 1],
          }}
        >
          {sceneContent()}
        </motion.div>
      </AnimatePresence>

      <div
        className="step-indicator"
        aria-hidden="true"
      >
        {Array.from({
          length: presentation.maxStep + 1,
        }).map((_, index) => (
          <span
            key={index}
            className={
              index <= presentation.step
                ? 'step-dot active'
                : 'step-dot'
            }
          />
        ))}
      </div>
    </div>
  );
}

export default App;
