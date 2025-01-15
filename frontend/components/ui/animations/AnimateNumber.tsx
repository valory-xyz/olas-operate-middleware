import { motion, useSpring } from 'framer-motion';
import { isNil } from 'lodash';
import React, { useEffect, useState } from 'react';

import { Maybe } from '@/types/Util';
import { balanceFormat } from '@/utils/numberFormatters';

type AnimatedNumberProps = {
  value: Maybe<number>;
  formatter?: (value: number) => string;
  hasAnimated?: boolean;
};

/**
 * Animate the number from 0 to the given value.
 */
export const AnimateNumber = ({
  value,
  formatter = balanceFormat,
  hasAnimated = false,
}: AnimatedNumberProps) => {
  const [displayValue, setDisplayValue] = useState(0);

  const springValue = useSpring(0, { stiffness: 150, damping: 25 });

  useEffect(() => {
    if (hasAnimated) {
      setDisplayValue(value || 0);
    } else {
      if (!isNil(value)) {
        springValue.set(value);
      }
    }
  }, [value, springValue, hasAnimated]);

  useEffect(() => {
    if (!hasAnimated && !isNil(value)) {
      springValue.set(value);
    }
  }, [value, springValue, hasAnimated]);

  useEffect(() => {
    if (!hasAnimated) {
      let lastUpdate = Date.now();

      const unsubscribe = springValue.on('change', (latest) => {
        const now = Date.now();

        // Only update the state at most every 100ms
        if (now - lastUpdate > 100) {
          lastUpdate = now;
          setDisplayValue(parseFloat(latest.toFixed(2)));
        }
      });

      return () => unsubscribe();
    }
  }, [springValue, hasAnimated]);

  return (
    <motion.span>
      {formatter ? formatter(displayValue) : displayValue}
    </motion.span>
  );
};
