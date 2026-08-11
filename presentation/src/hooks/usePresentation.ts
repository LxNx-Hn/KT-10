import { useCallback, useEffect, useMemo, useState } from 'react';

const SCENE_MAX_STEPS = [5, 2, 2, 3, 3, 2, 4, 4, 3, 4, 4, 3, 4];

export function usePresentation() {
  const [scene, setScene] = useState(0);
  const [step, setStep] = useState(0);

  const maxStep = useMemo(
    () => SCENE_MAX_STEPS[scene] ?? 0,
    [scene],
  );

  const next = useCallback(() => {
    const currentMax = SCENE_MAX_STEPS[scene] ?? 0;

    if (step < currentMax) {
      setStep((current) => current + 1);
      return;
    }

    if (scene < SCENE_MAX_STEPS.length - 1) {
      setScene((current) => current + 1);
      setStep(0);
    }
  }, [scene, step]);

  const previous = useCallback(() => {
    if (step > 0) {
      setStep((current) => current - 1);
      return;
    }

    if (scene > 0) {
      const previousScene = scene - 1;

      setScene(previousScene);
      setStep(SCENE_MAX_STEPS[previousScene] ?? 0);
    }
  }, [scene, step]);

  const resetScene = useCallback(() => {
    setStep(0);
  }, []);

  const resetAll = useCallback(() => {
    setScene(0);
    setStep(0);
  }, []);

  const goToScene = useCallback((targetScene: number) => {
    if (
      targetScene >= 0 &&
      targetScene < SCENE_MAX_STEPS.length
    ) {
      setScene(targetScene);
      setStep(0);
    }
  }, []);

  const toggleFullscreen = useCallback(async () => {
    try {
      if (!document.fullscreenElement) {
        await document.documentElement.requestFullscreen();
      } else {
        await document.exitFullscreen();
      }
    } catch {
      // 전체화면이 제한되더라도 발표 진행은 유지
    }
  }, []);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (
        event.code === 'Space' ||
        event.key === 'ArrowRight' ||
        event.key === 'PageDown'
      ) {
        event.preventDefault();
        next();
        return;
      }

      if (
        event.key === 'ArrowLeft' ||
        event.key === 'PageUp'
      ) {
        event.preventDefault();
        previous();
        return;
      }

      if (event.key.toLowerCase() === 'r') {
        event.preventDefault();
        resetScene();
        return;
      }

      if (event.key.toLowerCase() === 'h') {
        event.preventDefault();
        resetAll();
        return;
      }

      if (event.key.toLowerCase() === 'f') {
        event.preventDefault();
        void toggleFullscreen();
        return;
      }

      if (event.key === '0') {
        goToScene(9);
        return;
      }

      if (/^[1-9]$/.test(event.key)) {
        const target = Number(event.key) - 1;
        goToScene(target);
      }
    };

    window.addEventListener('keydown', handleKeyDown);

    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [
    goToScene,
    next,
    previous,
    resetAll,
    resetScene,
    toggleFullscreen,
  ]);

  return {
    scene,
    step,
    maxStep,
    next,
    previous,
    resetScene,
    resetAll,
    toggleFullscreen,
    goToScene,
  };
}
