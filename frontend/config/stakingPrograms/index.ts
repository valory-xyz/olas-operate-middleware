import { Contract as MulticallContract } from 'ethers-multicall';

import { AgentType } from '@/enums/Agent';
import { ChainId } from '@/enums/Chain';

import { MechType } from '../mechs';
import { GNOSIS_STAKING_PROGRAMS } from './gnosis';
import { OPTIMISM_STAKING_PROGRAMS } from './optimism';

/**
 * Single non-chain specific staking program configuration
 */
export type StakingProgramConfig = {
  chainId: ChainId;
  deprecated?: boolean; // hides program from UI unless user is already staked in this program
  name: string;
  agentsSupported: AgentType[];
  stakingRequirements: {
    [tokenSymbol: string]: number;
  };
  mech?: MechType;
  contract: MulticallContract;
};

export type StakingProgramMap = {
  [stakingProgramId: string]: StakingProgramConfig;
};

export const STAKING_PROGRAMS: StakingProgramMap = {
  ...GNOSIS_STAKING_PROGRAMS,
  ...OPTIMISM_STAKING_PROGRAMS,
};
