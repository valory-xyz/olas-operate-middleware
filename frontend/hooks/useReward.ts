import { useContext } from 'react';

import { RewardContext } from '@/context/RewardProvider';

export const useReward = () => {
  const {
    availableRewardsForEpoch,
    availableRewardsForEpochEth,
    isEligibleForRewards,
    accruedServiceStakingRewards,
    isStakingRewardsDetailsLoading,
    isStakingRewardsDetailsError,
  } = useContext(RewardContext);

  return {
    availableRewardsForEpoch,
    availableRewardsForEpochEth,
    isEligibleForRewards,
    accruedServiceStakingRewards,
    isStakingRewardsDetailsLoading,
    isStakingRewardsDetailsError,
  };
};
