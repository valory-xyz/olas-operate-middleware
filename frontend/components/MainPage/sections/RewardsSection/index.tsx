import { Flex, Skeleton, Tag, Typography } from 'antd';
import { AnimatePresence, HTMLMotionProps, motion } from 'framer-motion';
import { useMemo } from 'react';
import styled from 'styled-components';

import { NA } from '@/constants/symbols';
import { useBalanceContext } from '@/hooks/useBalanceContext';
import { useFeatureFlag } from '@/hooks/useFeatureFlag';
import { useRewardContext } from '@/hooks/useRewardContext';
import { balanceFormat } from '@/utils/numberFormatters';

import { CardSection } from '../../../styled/CardSection';
import { NotifyRewardsModal } from './NotifyRewardsModal';
import { RewardsStreak } from './RewardsStreak';
import { StakingRewardsThisEpoch } from './StakingRewardsThisEpoch';

const { Text } = Typography;

// Common motion props for the earned tag
const commonMotionProps: HTMLMotionProps<'div'> = {
  initial: 'initial',
  animate: 'animate',
  exit: 'exit',
  variants: {
    initial: { y: 10, opacity: 0 },
    animate: { y: 0, opacity: 1, transition: { duration: 0.5 } },
    exit: {
      y: -10,
      opacity: 0,
      transition: { duration: 0.5 },
    },
  },
  style: { position: 'absolute' },
};

const EarnedTagContainer = styled.div`
  position: relative;
  top: -14px;
`;

const Loader = () => (
  <Flex vertical gap={8}>
    <Skeleton.Button active size="small" style={{ width: 92 }} />
    <Skeleton.Button active size="small" style={{ width: 92 }} />
  </Flex>
);

const DisplayRewards = () => {
  const {
    availableRewardsForEpochEth: reward,
    isEligibleForRewards,
    isStakingRewardsDetailsLoading,
    isStakingRewardsDetailsError,
  } = useRewardContext();
  const { isLoaded: isBalancesLoaded } = useBalanceContext();
  const formattedReward =
    reward === undefined ? NA : `~${balanceFormat(reward, 2)}`;

  const earnedTag = useMemo(() => {
    if (isStakingRewardsDetailsLoading && !isStakingRewardsDetailsError) {
      return <Skeleton.Input size="small" />;
    }

    return (
      <AnimatePresence>
        {isEligibleForRewards ? (
          <motion.div key="earned" {...commonMotionProps}>
            <Tag color="success">Earned</Tag>
          </motion.div>
        ) : (
          <motion.div key="not-earned" {...commonMotionProps}>
            <Tag color="processing">Not yet earned</Tag>
          </motion.div>
        )}
      </AnimatePresence>
    );
  }, [
    isEligibleForRewards,
    isStakingRewardsDetailsLoading,
    isStakingRewardsDetailsError,
  ]);

  return (
    <CardSection vertical gap={8} padding="16px 24px" align="start">
      <StakingRewardsThisEpoch />
      {isBalancesLoaded ? (
        <Flex align="center" gap={12}>
          <Text className="text-xl font-weight-600">
            {formattedReward} OLAS&nbsp;
          </Text>
          <EarnedTagContainer>{earnedTag}</EarnedTagContainer>
        </Flex>
      ) : (
        <Loader />
      )}
    </CardSection>
  );
};

/**
 * Rewards (Earned OLAS and Tag) including the rewards modal.
 */
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
