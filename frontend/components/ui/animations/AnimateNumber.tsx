import { motion, useSpring } from 'framer-motion';
import { isNil } from 'lodash';
import React, { useEffect, useState } from 'react';

import { Maybe } from '@/types/Util';
import { balanceFormat } from '@/utils/numberFormatters';

type AnimatedNumberProps = {
  value: Maybe<number>;
  formatter?: (value: number) => string;
  triggerAnimation?: boolean;
  onAnimationChange?: (isAnimating: boolean) => void;
};

/**
 * Animate the number from 0 to the given value.
 */
export const AnimateNumber = ({
  value,
  formatter = balanceFormat,
  triggerAnimation = true,
  onAnimationChange,
}: AnimatedNumberProps) => {
  const [displayValue, setDisplayValue] = useState(isNil(value) ? 0 : value);
  const springValue = useSpring(0, { stiffness: 150, damping: 25 });

  useEffect(() => {
    if (isNil(value)) return;

    if (triggerAnimation) {
      springValue.set(value);
    } else {
      setDisplayValue(value);
    }
  }, [value, springValue, triggerAnimation]);

  // Handle animation updates and completion
  useEffect(() => {
    if (!triggerAnimation) return;

    let lastUpdate = Date.now();
    const threshold = 0.01; // Precision threshold to detect completion

    const unsubscribe = springValue.on('change', (latest) => {
      const now = Date.now();

      // Update display value periodically
      if (now - lastUpdate > 100) {
        lastUpdate = now;
        setDisplayValue(parseFloat(latest.toFixed(2)));
      }

      // Notify animation change
      if (onAnimationChange) {
        const isAnimating = Math.abs(latest - (value ?? 0)) >= threshold;
        onAnimationChange(isAnimating);
      }
    });

    return () => unsubscribe();
  }, [springValue, value, triggerAnimation, onAnimationChange]);

  return (
    <motion.span>
      {formatter ? formatter(displayValue) : displayValue}
    </motion.span>
  );
};
