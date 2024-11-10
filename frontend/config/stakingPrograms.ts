/**
 * Staking program configurations by chain
 * @note Add new staking programs here
 * @note Deprecated programs are hidden from the UI unless the user is already staked in the program
 * @note Supported agents are the agents that can stake in the program
 * @note Staking requirements are the minimum amount of tokens required to stake in staking program
 * @note Update chain specfic configs only
 * @note If creating a new chain, add a new key to the STAKING_PROGRAM_CONFIG object
 */

import { AgentType } from '@/enums/Agent';
import { ChainId } from '@/enums/Chain';
import { StakingProgramId } from '@/enums/StakingProgram';
import { TokenSymbol } from '@/enums/Token';

/**
 * Single non-chain specific staking program configuration
 */
export type StakingProgramConfig = {
  deprecated?: boolean; // hides program from UI unless user is already staked in this program
  name: string;
  supportedAgents: AgentType[];
  stakingRequirements?: {
    [tokenSymbol: string | TokenSymbol]: number;
  };
};

/**
 * Staking program configurations by staking program id
 * @note Add new staking programs here
 * @note Used to type chain specific staking program configs
 */
type StakingProgramConfigs = {
  [stakingProgramId: string | StakingProgramId]: StakingProgramConfig;
};

const GNOSIS_STAKING_PROGRAM_CONFIG: StakingProgramConfigs = {
  [StakingProgramId.PearlAlpha]: {
    deprecated: true,
    name: 'Pearl Alpha',
    supportedAgents: [AgentType.PredictTrader],
    stakingRequirements: {
      [TokenSymbol.OLAS]: 20,
    },
  },
  [StakingProgramId.PearlBeta]: {
    name: 'Pearl Beta',
    supportedAgents: [AgentType.PredictTrader],
    stakingRequirements: {
      [TokenSymbol.OLAS]: 40,
    },
  },
  [StakingProgramId.PearlBeta2]: {
    name: 'Pearl Beta 2',
    supportedAgents: [AgentType.PredictTrader],
    stakingRequirements: {
      [TokenSymbol.OLAS]: 100,
    },
  },
  [StakingProgramId.PearlBeta3]: {
    name: 'Pearl Beta 3',
    supportedAgents: [AgentType.PredictTrader],
    stakingRequirements: {
      [TokenSymbol.OLAS]: 100,
    },
  },
  [StakingProgramId.PearlBeta4]: {
    name: 'Pearl Beta 4',
    supportedAgents: [AgentType.PredictTrader],
    stakingRequirements: {
      [TokenSymbol.OLAS]: 100,
    },
  },
  [StakingProgramId.PearlBeta5]: {
    name: 'Pearl Beta 5',
    supportedAgents: [AgentType.PredictTrader],
    stakingRequirements: {
      [TokenSymbol.OLAS]: 10,
    },
  },
  [StakingProgramId.PearlBetaMechMarketplace]: {
    name: 'Pearl Beta Mech Marketplace',
    supportedAgents: [AgentType.PredictTrader],
    stakingRequirements: {
      [TokenSymbol.OLAS]: 40,
    },
  },
};

const OPTIMISM_STAKING_PROGRAM_CONFIG = {
  [StakingProgramId.OptimusAlpha]: {
    id: 'optimus_alpha',
    name: 'Optimus Alpha',
    supportedAgents: [AgentType.Optimus],
    stakingRequirements: {
      [TokenSymbol.OLAS]: 40,
    },
  },
};

type StakingProgramConfigsByChain = {
  [chainId: number | ChainId]: StakingProgramConfigs;
};
export const STAKING_PROGRAM_CONFIG: StakingProgramConfigsByChain = {
  [ChainId.Gnosis]: GNOSIS_STAKING_PROGRAM_CONFIG,
  [ChainId.Optimism]: OPTIMISM_STAKING_PROGRAM_CONFIG,
};
