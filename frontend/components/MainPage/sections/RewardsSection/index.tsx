import { Flex, Skeleton, Tag, Typography } from 'antd';
import { AnimatePresence, HTMLMotionProps, motion } from 'framer-motion';
import { useMemo, useState } from 'react';

import { NA } from '@/constants/symbols';
import { useBalanceContext } from '@/hooks/useBalanceContext';
import { useFeatureFlag } from '@/hooks/useFeatureFlag';
import { useReward } from '@/hooks/useReward';
import { balanceFormat } from '@/utils/numberFormatters';

import { CardSection } from '../../../styled/CardSection';
import { NotifyRewardsModal } from './NotifyRewardsModal';
import { RewardsStreak } from './RewardsStreak';
import { StakingRewardsThisEpoch } from './StakingRewardsThisEpoch';

const { Text } = Typography;

// Variants for animations
const tagVariants = {
  initial: { y: 10, opacity: 0 },
  animate: { y: 0, opacity: 1, transition: { duration: 0.5 } },
  exit: {
    y: -10,
    opacity: 0,
    transition: { duration: 0.5 },
  },
};

const Loader = () => (
  <Flex vertical gap={8}>
    <Skeleton.Button active size="small" style={{ width: 92 }} />
    <Skeleton.Button active size="small" style={{ width: 92 }} />
  </Flex>
);

const getFormattedReward = (reward: number | undefined) =>
  reward === undefined ? NA : `~${balanceFormat(reward, 2)}`;

const DisplayRewards = () => {
  const {
    availableRewardsForEpochEth,
    isEligibleForRewards,
    isStakingRewardsDetailsLoading,
    isStakingRewardsDetailsError,
  } = useReward();
  const { isLoaded: isBalancesLoaded } = useBalanceContext();
  const reward = getFormattedReward(availableRewardsForEpochEth);

  const [someValue, setSomeValue] = useState(0);
  const [showEarned, setShowEarned] = useState(false);

  // after 5 seconds, set someValue to 1
  setTimeout(() => {
    setSomeValue(1);
    setShowEarned(true);
  }, 3000);

  const earnedTag = useMemo(() => {
    if (isStakingRewardsDetailsLoading && !isStakingRewardsDetailsError) {
      return <Skeleton.Input size="small" />;
    }

    const commonMotionProps: HTMLMotionProps<'div'> = {
      initial: 'initial',
      animate: 'animate',
      exit: 'exit',
      variants: tagVariants,
      style: { position: 'absolute' },
    };

    if ((isEligibleForRewards || someValue === 1) && showEarned) {
      return (
        <AnimatePresence>
          <motion.div key="earned" custom="up" {...commonMotionProps}>
            <Tag color="success">Earned</Tag>
          </motion.div>
        </AnimatePresence>
      );
    }

    return (
      <AnimatePresence onExitComplete={() => setShowEarned(true)}>
        <motion.div key="not-earned" custom="down" {...commonMotionProps}>
          <Tag color="processing">Not yet earned</Tag>
        </motion.div>
      </AnimatePresence>
    );
  }, [
    isEligibleForRewards,
    isStakingRewardsDetailsLoading,
    isStakingRewardsDetailsError,
    someValue,
    showEarned,
  ]);

  return (
    <CardSection vertical gap={8} padding="16px 24px" align="start">
      <StakingRewardsThisEpoch />
      {isBalancesLoaded ? (
        <Flex align="center" gap={12}>
          <Text className="text-xl font-weight-600">{reward} OLAS&nbsp;</Text>
          <div style={{ position: 'relative', top: -14 }}>{earnedTag}</div>
        </Flex>
      ) : (
        <Loader />
      )}
    </CardSection>
  );
};

export const RewardsSection = () => {
  const isRewardsStreakEnabled = useFeatureFlag('rewards-streak');

  return (
    <>
      <DisplayRewards />
      {isRewardsStreakEnabled && <RewardsStreak />}
      <NotifyRewardsModal />
    </>
  );
};
