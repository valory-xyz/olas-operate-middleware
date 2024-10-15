import { useQuery } from '@tanstack/react-query';
import { ethers } from 'ethers';
import { gql, request } from 'graphql-request';
import { groupBy } from 'lodash';
import { useMemo } from 'react';
import { z } from 'zod';

import { Chain } from '@/client';
import { SERVICE_STAKING_TOKEN_MECH_USAGE_CONTRACT_ADDRESSES } from '@/constants/contractAddresses';
import { STAKING_PROGRAM_META } from '@/constants/stakingProgramMeta';
import { SUBGRAPH_URL } from '@/constants/urls';
import { StakingProgramId } from '@/enums/StakingProgram';

import {
  EpochDetails,
  StakingRewardSchema,
} from '../components/RewardsHistory/types';

const ONE_DAY_IN_S = 24 * 60 * 60;
const ONE_DAY_IN_MS = ONE_DAY_IN_S * 1000;

const RewardHistoryResponseSchema = z.object({
  epoch: z.string(),
  rewards: z.array(z.string()),
  serviceIds: z.array(z.string()),
  blockTimestamp: z.string(),
  transactionHash: z.string(),
  epochLength: z.string(),
});
type RewardHistoryResponse = z.infer<typeof RewardHistoryResponseSchema>;

const betaAddress =
  SERVICE_STAKING_TOKEN_MECH_USAGE_CONTRACT_ADDRESSES[Chain.GNOSIS].pearl_beta;
const beta2Address =
  SERVICE_STAKING_TOKEN_MECH_USAGE_CONTRACT_ADDRESSES[Chain.GNOSIS]
    .pearl_beta_2;

const fetchRewardsQuery = gql`
  {
    allRewards: checkpoints(orderBy: epoch, orderDirection: desc) {
      blockTimestamp
      availableRewards
      epoch
      epochLength
      id
      rewards
      serviceIds
      transactionHash
      contractAddress
    }
  }
`;

const transformRewards = (
  rewards: RewardHistoryResponse[],
  serviceId?: number,
  timestampToIgnore?: null | number,
) => {
  if (!rewards || rewards.length === 0) return [];
  if (!serviceId) return [];

  return rewards
    .map((currentReward: RewardHistoryResponse, index: number) => {
      const {
        epoch,
        rewards: aggregatedServiceRewards,
        serviceIds,
        epochLength,
        blockTimestamp,
        transactionHash,
      } = RewardHistoryResponseSchema.parse(currentReward);
      const serviceIdIndex = serviceIds.findIndex(
        (id) => Number(id) === serviceId,
      );
      const reward =
        serviceIdIndex === -1 ? 0 : aggregatedServiceRewards[serviceIdIndex];

      // If the epoch is 0, it means it's the first epoch else,
      // the start time of the epoch is the end time of the previous epoch
      const epochStartTimeStamp =
        epoch === '0'
          ? Number(blockTimestamp) - Number(epochLength)
          : rewards[index + 1].blockTimestamp;

      return {
        epochEndTimeStamp: Number(blockTimestamp),
        epochStartTimeStamp: Number(epochStartTimeStamp),
        reward: Number(ethers.utils.formatUnits(reward, 18)),
        earned: serviceIdIndex !== -1,
        transactionHash,
      } as EpochDetails;
    })
    .filter((epoch) => {
      // If the contract has been switched to new contract, ignore the rewards from the old contract of the same epoch,
      // as the rewards are already accounted in the new contract.
      // example: If contract was switched on September 1st, 2024, ignore the rewards before that date
      // in the old contract.
      if (!timestampToIgnore) return true;
      return epoch.epochEndTimeStamp < timestampToIgnore;
    });
};

/**
 * Get the timestamp of the first reward received by the service in the contract.
 * NOTE: Assumes that the switch of the contract was completed AND the rewards are received in the same epoch.
 */
const getTimestampOfFirstReward = (
  epochs: RewardHistoryResponse[],
  serviceId: number,
) => {
  const timestamp = epochs
    .toReversed()
    .find((epochDetails) =>
      epochDetails.serviceIds.includes(`${serviceId}`),
    )?.blockTimestamp;

  return timestamp ? Number(timestamp) : null;
};

export const useRewardsHistory = () => {
  // const { serviceId } = useServices();
  const serviceId = 639;
  const { data, isError, isLoading, isFetching, refetch } = useQuery({
    queryKey: [],
    async queryFn() {
      const allRewardsResponse = await request(SUBGRAPH_URL, fetchRewardsQuery);
      return allRewardsResponse as { allRewards: RewardHistoryResponse[] };
    },
    select: (data) => {
      const allRewards = groupBy(data.allRewards, 'contractAddress');
      const beta2Rewards = allRewards[beta2Address.toLowerCase()];
      /** Pearl beta 2 details */

      // timestamp when the contract was switched to beta2
      // ie, got the fist rewards from beta2 contract
      const beta2switchTimestamp = getTimestampOfFirstReward(
        beta2Rewards,
        serviceId as number,
      );
      const beta2ContractDetails = {
        id: beta2Address,
        name: STAKING_PROGRAM_META[StakingProgramId.Beta2].name,
        history: transformRewards(beta2Rewards, serviceId, null),
      };

      /** Pearl beta details */
      const betaRewards = allRewards[betaAddress.toLowerCase()];
      const betaContractRewards = {
        id: betaAddress,
        name: STAKING_PROGRAM_META[StakingProgramId.Beta].name,
        history: transformRewards(betaRewards, serviceId, beta2switchTimestamp),
      };

      // If there are no rewards in both contracts, return empty array
      const rewards = [];
      if (beta2ContractDetails.history.some((epoch) => epoch.earned)) {
        rewards.push(beta2ContractDetails);
      }
      if (betaContractRewards.history.some((epoch) => epoch.earned)) {
        rewards.push(betaContractRewards);
      }

      const parsedRewards = StakingRewardSchema.array().safeParse(rewards);
      if (!parsedRewards.success) {
        throw new Error(parsedRewards.error.errors.join(', '));
      }

      return parsedRewards.data;
    },
    refetchOnWindowFocus: false,
    refetchInterval: ONE_DAY_IN_MS,
    enabled: !!serviceId,
  });

  const latestRewardStreak = useMemo<number | null>(() => {
    if (!data) return null;

    // merge histories into single array
    const allHistories = data.reduce(
      (acc, { history }) => [...acc, ...history],
      [] as EpochDetails[],
    );

    // remove all histories that are not earned
    const earnedHistories = allHistories.filter((history) => history.earned);

    // sort descending by epoch end time
    const sorted = earnedHistories.sort(
      (a, b) => b.epochEndTimeStamp - a.epochEndTimeStamp,
    );

    let streak = 0;
    for (let i = 0; i < sorted.length; i++) {
      const current = sorted[i];
      // 1st iteration
      if (i == 0) {
        current.earned && streak++;
        continue;
      }

      const previous = sorted[i - 1];

      // 2nd iteration should consider that the
      // first element may not have been earned yet
      if (i == 1) {
        if (!current.earned) break;
        streak++;
        continue;
      }

      // nth iterations should compare the time difference between epochs to detect streaks
      if (!previous.earned) break;
      if (!current.earned) break;

      const epochGap = previous.epochEndTimeStamp - current.epochStartTimeStamp;

      // if the gap between epochs is more than 1 day, break the loop
      if (epochGap > ONE_DAY_IN_S) break;

      // if the gap between epochs is less than 1 day, increment the streak
      current.earned && streak++;
    }

    return streak;
  }, [data]);

  return {
    isError,
    isFetching,
    isLoading,
    latestRewardStreak,
    refetch,
    rewards: data,
  };
};
