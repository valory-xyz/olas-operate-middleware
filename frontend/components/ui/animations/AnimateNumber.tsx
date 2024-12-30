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
const AnimatedNumber = ({
  value,
  formatter = balanceFormat,
}: AnimatedNumberProps) => {
  const springValue = useSpring(0, {
    stiffness: 120, // Adjust to control how quickly it moves
    damping: 20, // Adjust for smooth deceleration
  });

  const [displayValue, setDisplayValue] = useState(0);

  // Update spring target whenever value changes
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

  return <motion.div>{formatter(displayValue)}</motion.div>;
};

export const AnimatedNumberExample = () => {
  const [earned, setEarned] = React.useState<number | null>(null);

  useEffect(() => {
    // Simulate initial value setting
    const timer1 = setTimeout(() => setEarned(0), 1000);
    // Simulate an update to the "earned" value
    const timer2 = setTimeout(() => setEarned(90.45), 3000);

    return () => {
      clearTimeout(timer1);
      clearTimeout(timer2);
    };
  }, []);

  // setinterval every 3 seconds to random value between 0 and 100
  // useEffect(() => {
  //   const interval = setInterval(() => {
  //     setEarned(Math.random() * 100);
  //   }, 3000);
  //   return () => clearInterval(interval);
  // }, []);

  return (
    <div>
      <div>Earned Amount </div>
      <AnimatedNumber value={earned} />
    </div>
  );
};
