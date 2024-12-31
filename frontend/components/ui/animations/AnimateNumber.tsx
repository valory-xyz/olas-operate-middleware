import { motion, useSpring } from 'framer-motion';
import { isNil } from 'lodash';
import React, { useEffect, useState } from 'react';

import { balanceFormat } from '@/utils/numberFormatters';

type AnimatedNumberProps = {
  value: number | null;
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

  const springValue = useSpring(0, { stiffness: 120, damping: 20 });

  useEffect(() => {
    if (!isNil(value)) {
      springValue.set(value);
    }
  }, [value, springValue]);

  // Listen to the spring value changes
  useEffect(() => {
    const unsubscribe = springValue.on('change', (latest) => {
      setDisplayValue(parseFloat(latest.toFixed(2)));
    });

    return () => unsubscribe();
  }, [springValue]);

  return (
    <motion.span>
      {formatter ? formatter(displayValue) : displayValue}
    </motion.span>
  );
};
