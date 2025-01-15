import { motion, useSpring } from 'framer-motion';
import { isNil } from 'lodash';
import React, { useEffect, useState } from 'react';

import { usePrevious } from '@/hooks/usePrevious';
import { Maybe } from '@/types/Util';
import { balanceFormat } from '@/utils/numberFormatters';

type AnimatedNumberProps = {
  value: Maybe<number>;
  formatter?: (value: number) => string;
  hasAnimatedOnFirstLoad: boolean; // Whether the animation has already been triggered
};

/**
 * Animate the number from 0 to the given value.
 */
export const AnimateNumber = ({
  value,
  formatter = balanceFormat,
  hasAnimatedOnFirstLoad,
}: AnimatedNumberProps) => {
  const [displayValue, setDisplayValue] = useState(0);
  const springValue = useSpring(0, { stiffness: 150, damping: 25 });
  const previousValue = usePrevious(value);

  // console.log({ previousValue, value, displayValue, hasAnimatedOnFirstLoad });

  // Detect changes and animate if the value is different from the previous one
  useEffect(() => {
    if (isNil(value)) return;

    console.log('value changed', { value, displayValue, previousValue });

    if (value !== previousValue) {
      springValue.set(value);
      // setDisplayValue(value);
      return;
    }

    // if (hasAnimatedOnFirstLoad) {
    //   setDisplayValue(value);
    // }

    // setDisplayValue(value);
  }, [value, springValue, hasAnimatedOnFirstLoad, previousValue]);

  useEffect(() => {
    // Skip animation if already animated
    // if (hasAnimatedOnFirstLoad && displayValue === previousValue) return;

    // Skip animation if value hasn't changed
    // if (isNil(displayValue) || displayValue === previousValue) return;
    console.log('start animation', {
      hasAnimatedOnFirstLoad,
      value,
      displayValue,
      previousValue,
      turrr: displayValue === previousValue,
    });

    if (!hasAnimatedOnFirstLoad || value !== displayValue) {
      console.log('HERE');
      console.log('--------------------------------------------------');
      console.log('--------------------------------------------------');
      let lastUpdate = Date.now();
      const unsubscribe = springValue.on('change', (latest) => {
        const now = Date.now();
        if (now - lastUpdate > 100) {
          lastUpdate = now;
          setDisplayValue(parseFloat(latest.toFixed(2)));
        }
      });

      return () => unsubscribe();
    }
  }, [springValue, hasAnimatedOnFirstLoad, previousValue, value, displayValue]);

  return (
    <motion.span>
      {formatter ? formatter(displayValue) : displayValue}
    </motion.span>
  );
};
