import { motion, useSpring } from 'framer-motion';
import { isNil } from 'lodash';
import React, { useEffect, useMemo, useState } from 'react';

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
  const previousValue = usePrevious(value || 0);

  const isValidNumberToAnimate = useMemo(() => {
    // if (isNil(value)) return;
    // if (isNil(previousValue)) return;
    // if (value === 0 || previousValue === 0) return;

    return true;
  }, [value, previousValue]);

  useEffect(() => {
    if (isNil(value)) return;

    // Current value is different from the previous value
    if (value !== previousValue) {
      if (!isValidNumberToAnimate) return;
      springValue.set(value);
      return;
    }

    // console.log('value', value);

    // Set the display value to the new value if the animation has already been triggered
    if (hasAnimatedOnFirstLoad) {
      // setDisplayValue(value);
      return;
    }
  }, [
    value,
    springValue,
    hasAnimatedOnFirstLoad,
    previousValue,
    isValidNumberToAnimate,
  ]);

  useEffect(() => {
    console.log({ value, previousValue });

    // Skip animation if
    // - already animated
    // - the value is the same as the previous value
    if (hasAnimatedOnFirstLoad && value === previousValue) return;

    if (hasAnimatedOnFirstLoad) {
      if (!isValidNumberToAnimate) return;
    }

    let lastUpdate = Date.now();
    const unsubscribe = springValue.on('change', (latest) => {
      const now = Date.now();
      if (now - lastUpdate > 100) {
        lastUpdate = now;
        setDisplayValue(parseFloat(latest.toFixed(2)));
      }
    });

    return () => unsubscribe();
  }, [
    springValue,
    hasAnimatedOnFirstLoad,
    previousValue,
    value,
    isValidNumberToAnimate,
  ]);

  return (
    <motion.span>
      {formatter ? formatter(displayValue) : displayValue}
    </motion.span>
  );
};
