import { motion, useSpring } from 'framer-motion';
import { isNil } from 'lodash';
import React, { useEffect, useState } from 'react';

import { Nullable } from '@/types/Util';
import { balanceFormat } from '@/utils/numberFormatters';

type AnimatedNumberProps = {
  value: Nullable<number>;
  formatter?: (value: number) => string;
};

/**
 * Animate the number from 0 to the given value.
 */
export const AnimateNumber = ({
  value,
  formatter = balanceFormat,
}: AnimatedNumberProps) => {
  const [displayValue, setDisplayValue] = useState(0);

  const springValue = useSpring(0, { stiffness: 150, damping: 25 });

  useEffect(() => {
    if (!isNil(value)) {
      springValue.set(value);
    }
  }, [value, springValue]);

  useEffect(() => {
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
  }, [springValue]);

  return (
    <motion.span>
      {formatter ? formatter(displayValue) : displayValue}
    </motion.span>
  );
};
