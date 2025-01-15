import { motion, useSpring } from 'framer-motion';
import { isNil } from 'lodash';
import React, { useEffect, useState } from 'react';

import { Maybe } from '@/types/Util';
import { balanceFormat } from '@/utils/numberFormatters';

type AnimatedNumberProps = {
  value: Maybe<number>;
  formatter?: (value: number) => string;
  triggerAnimation?: boolean;
};

/**
 * Animate the number from 0 to the given value.
 */
export const AnimateNumber = ({
  value,
  formatter = balanceFormat,
  triggerAnimation = true,
}: AnimatedNumberProps) => {
  const [displayValue, setDisplayValue] = useState(0);
  const springValue = useSpring(0, { stiffness: 150, damping: 25 });

  useEffect(() => {
    if (isNil(value)) return;

    if (triggerAnimation) {
      springValue.set(value);
    } else {
      setDisplayValue(value);
    }
  }, [value, springValue, triggerAnimation]);

  useEffect(() => {
    if (!triggerAnimation) return;

    let lastUpdate = Date.now();
    const unsubscribe = springValue.on('change', (latest) => {
      const now = Date.now();
      if (now - lastUpdate > 100) {
        lastUpdate = now;
        setDisplayValue(parseFloat(latest.toFixed(2)));
      }
    });

    return () => unsubscribe();
  }, [springValue, value, triggerAnimation]);

  return (
    <motion.span>
      {formatter ? formatter(displayValue) : displayValue}
    </motion.span>
  );
};
