import { AgentType } from '@/enums/Agent';
import { ChainId } from '@/enums/Chain';
import { StakingProgramId } from '@/enums/StakingProgram';
import { TokenSymbol } from '@/enums/Token';

const GNOSIS_STAKING_PROGRAM_CONFIG: {
  [stakingProgramId: string | StakingProgramId]: {
    deprecated?: boolean; // hides program from UI unless user is already staked in this program
    name: string;
    supportedAgents: AgentType[];
    stakingRequirements?: {
      [tokenSymbol: string]: number;
    };
  };
} = {
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

export const STAKING_PROGRAM_CONFIG = {
  [ChainId.Gnosis]: GNOSIS_STAKING_PROGRAM_CONFIG,
  [ChainId.Optimism]: OPTIMISM_STAKING_PROGRAM_CONFIG,
};
