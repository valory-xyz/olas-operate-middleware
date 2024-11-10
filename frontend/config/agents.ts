import { AgentType } from '@/enums/Agent';
import { ChainId } from '@/enums/Chain';
import { OptimusService } from '@/service/agents/Optimus';
import { PredictTraderService } from '@/service/agents/PredictTrader';

export const AGENT_CONFIG = {
  [AgentType.PredictTrader]: {
    name: 'Predict Trader',
    homeChainId: ChainId.Gnosis,
    requiresAgentSafesOn: [ChainId.Gnosis],
    requiresMasterSafesOn: [ChainId.Gnosis],
    serviceApi: PredictTraderService,
  },
  [AgentType.Optimus]: {
    name: 'Optimus',
    homeChainId: ChainId.Optimism,
    requiresAgentSafesOn: [ChainId.Optimism, ChainId.Ethereum, ChainId.Base],
    requiresMasterSafesOn: [ChainId.Optimism, ChainId.Ethereum, ChainId.Base],
    serviceApi: OptimusService,
  },
};
