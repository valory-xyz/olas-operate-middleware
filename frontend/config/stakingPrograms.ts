import { AgentType } from '@/enums/Agent';
import { ChainId } from '@/enums/Chain';
import { StakingProgramId } from '@/enums/StakingProgram';

const GNOSIS_STAKING_PROGRAM_CONFIG: {
  [stakingProgramId: string | StakingProgramId]: {
    name: string;
    supportedAgents: AgentType[];
    deprecated?: boolean; // hides program from UI unless user is already staked in this program
  };
} = {
  [StakingProgramId.PearlAlpha]: {
    deprecated: true,
    name: 'Pearl Alpha',
    supportedAgents: [AgentType.PredictTrader],
  },
  [StakingProgramId.PearlBeta]: {
    name: 'Pearl Beta',
    supportedAgents: [AgentType.PredictTrader],
  },
  [StakingProgramId.PearlBeta2]: {
    name: 'Pearl Beta 2',
    supportedAgents: [AgentType.PredictTrader],
  },
  [StakingProgramId.PearlBeta3]: {
    name: 'Pearl Beta 3',
    supportedAgents: [AgentType.PredictTrader],
  },
  [StakingProgramId.PearlBeta4]: {
    name: 'Pearl Beta 4',
    supportedAgents: [AgentType.PredictTrader],
  },
  [StakingProgramId.PearlBeta5]: {
    name: 'Pearl Beta 5',
    supportedAgents: [AgentType.PredictTrader],
  },
  [StakingProgramId.PearlBetaMechMarketplace]: {
    name: 'Pearl Beta Mech Marketplace',
    supportedAgents: [AgentType.PredictTrader],
  },
};

const OPTIMISM_STAKING_PROGRAM_CONFIG = {
  [StakingProgramId.OptimusAlpha]: {
    id: 'optimus_alpha',
    name: 'Optimus Alpha',
    supportedAgents: [AgentType.Optimus],
  },
};

export const STAKING_PROGRAM_CONFIG = {
  [ChainId.Gnosis]: GNOSIS_STAKING_PROGRAM_CONFIG,
  [ChainId.Optimism]: OPTIMISM_STAKING_PROGRAM_CONFIG,
};
