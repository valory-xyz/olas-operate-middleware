import { Address } from '@/types/Address';

export type EpochDetails = {
  epochStartTimeStamp: number;
  epochEndTimeStamp: number;
  reward: number;
  earned: boolean;
  transactionHash: string;
};

export type StakingReward = {
  id: Address;
  name: string;
  history: EpochDetails[];
};
