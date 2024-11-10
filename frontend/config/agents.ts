import { AgentType } from '@/enums/Agent';
import { OptimusService } from '@/service/agents/Optimus';
import { PredictTraderService } from '@/service/agents/PredictTrader';

export const AGENT_CONFIG = {
  [AgentType.PredictTrader]: {
    service: PredictTraderService,
  },
  [AgentType.Optimus]: {
    service: OptimusService,
  },
};
