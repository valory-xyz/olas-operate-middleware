import { animate, motion, useMotionValue, useTransform } from 'framer-motion';
import { isNil } from 'lodash';
import React, { useEffect } from 'react';

type AnimatedNumberProps = { earned: number | null };

const AnimatedNumber = ({ earned }: AnimatedNumberProps) => {
  const motionValue = useMotionValue(0);

  // Transform the motion value to a number with 2 decimals
  const animatedValue = useTransform(motionValue, (value) => value.toFixed(2));

  // Update the motion value whenever "earned" changes
  useEffect(() => {
    if (!isNil(earned)) {
      const controls = animate(motionValue, earned, {
        duration: 1, // Animation duration in seconds
        ease: 'easeOut',
      });
      return controls.stop; // Clean up animation on unmount
    }
  }, [earned, motionValue]);

  return <motion.div>{animatedValue}</motion.div>;
};

export const AnimatedNumberExample = () => {
  const [earned, setEarned] = React.useState<number | null>(null);

  useEffect(() => {
    // Simulate initial value setting
    const timer1 = setTimeout(() => setEarned(0), 1000);
    // Simulate an update to the "earned" value
    const timer2 = setTimeout(() => setEarned(123.45), 3000);

    return () => {
      clearTimeout(timer1);
      clearTimeout(timer2);
    };
  }, []);

  return (
    <div>
      <div>Earned Amount</div>
      <AnimatedNumber earned={earned} />
    </div>
  );
};
