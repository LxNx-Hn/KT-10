import { useReducedMotion } from 'framer-motion';

const easeOut = [0.22, 1, 0.36, 1] as const;

export const stepSwap = {
  initial: {
    opacity: 0,
    visibility: 'hidden' as const,
    pointerEvents: 'none' as const,
  },
  animate: {
    opacity: 1,
    visibility: 'visible' as const,
    pointerEvents: 'auto' as const,
    transition: {
      duration: 0.22,
      ease: easeOut,
    },
  },
  exit: {
    opacity: 0,
    visibility: 'hidden' as const,
    pointerEvents: 'none' as const,
    transition: {
      duration: 0.16,
      ease: easeOut,
    },
  },
};

const live = {
  staggerContainer: {
    hidden: {},
    show: {
      transition: {
        delayChildren: 0.08,
        staggerChildren: 0.08,
      },
    },
  },
  staggerItem: {
    hidden: { opacity: 0, y: 16 },
    show: {
      opacity: 1,
      y: 0,
      transition: { duration: 0.34, ease: easeOut },
    },
  },
  softRise: {
    hidden: { opacity: 0, y: 14 },
    show: {
      opacity: 1,
      y: 0,
      transition: { duration: 0.32, ease: easeOut },
    },
  },
  softScale: {
    hidden: { opacity: 0, y: 12, scale: 0.97 },
    show: {
      opacity: 1,
      y: 0,
      scale: 1,
      transition: { duration: 0.36, ease: easeOut },
    },
  },
  drawLine: {
    hidden: { opacity: 0, scaleX: 0 },
    show: {
      opacity: 1,
      scaleX: 1,
      transition: { duration: 0.32, ease: easeOut },
    },
  },
  fadeIn: {
    hidden: { opacity: 0 },
    show: {
      opacity: 1,
      transition: { duration: 0.3, ease: easeOut },
    },
  },
  numberReveal: {
    hidden: { opacity: 0, y: 10 },
    show: {
      opacity: 1,
      y: 0,
      transition: { duration: 0.3, ease: easeOut },
    },
  },
};

const reduced = {
  staggerContainer: {
    hidden: {},
    show: {
      transition: {
        delayChildren: 0,
        staggerChildren: 0,
      },
    },
  },
  staggerItem: {
    hidden: { opacity: 1, y: 0 },
    show: { opacity: 1, y: 0, transition: { duration: 0.01 } },
  },
  softRise: {
    hidden: { opacity: 1, y: 0 },
    show: { opacity: 1, y: 0, transition: { duration: 0.01 } },
  },
  softScale: {
    hidden: { opacity: 1, y: 0, scale: 1 },
    show: { opacity: 1, y: 0, scale: 1, transition: { duration: 0.01 } },
  },
  drawLine: {
    hidden: { opacity: 1, scaleX: 1 },
    show: { opacity: 1, scaleX: 1, transition: { duration: 0.01 } },
  },
  fadeIn: {
    hidden: { opacity: 1 },
    show: { opacity: 1, transition: { duration: 0.01 } },
  },
  numberReveal: {
    hidden: { opacity: 1, y: 0 },
    show: { opacity: 1, y: 0, transition: { duration: 0.01 } },
  },
};

export function useMotionVariants() {
  const reduce = useReducedMotion();
  return reduce ? reduced : live;
}

export const staggerContainer = live.staggerContainer;
export const staggerItem = live.staggerItem;
export const softRise = live.softRise;
export const softScale = live.softScale;
export const drawLine = live.drawLine;
export const fadeIn = live.fadeIn;
export const numberReveal = live.numberReveal;
