import { AgentType } from '@/enums/Agent';
import { ChainId } from '@/enums/Chain';
import { OptimusServiceApi } from '@/service/agents/Optimus';
import { PredictTraderServiceApi } from '@/service/agents/PredictTrader';

export const AGENT_CONFIG = {
  [AgentType.PredictTrader]: {
    name: 'Predict Trader',
    homeChainId: ChainId.Gnosis,
    requiresAgentSafesOn: [ChainId.Gnosis],
    requiresMasterSafesOn: [ChainId.Gnosis],
    serviceApi: PredictTraderServiceApi,
  },
  [AgentType.Optimus]: {
    name: 'Optimus',
    homeChainId: ChainId.Optimism,
    requiresAgentSafesOn: [ChainId.Optimism, ChainId.Ethereum, ChainId.Base],
    requiresMasterSafesOn: [ChainId.Optimism, ChainId.Ethereum, ChainId.Base],
    serviceApi: OptimusServiceApi,
  },
};
