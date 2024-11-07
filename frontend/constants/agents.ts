import { OptimusService } from '@/service/agents/Optimus';
import { PredictTraderService } from '@/service/agents/PredictTrader';

export const AGENT_CONFIG = {
  PREDICT_TRADER: {
    service: PredictTraderService,
  },
  OPTIMUS: {
    service: OptimusService,
  },
};
