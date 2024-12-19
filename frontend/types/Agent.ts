import { MiddlewareChain } from '@/client';
import { EvmChainId } from '@/enums/Chain';
import { TokenSymbol } from '@/enums/Token';
import { WalletOwnerType } from '@/enums/Wallet';
import { PredictTraderService } from '@/service/agents/PredictTrader';

export type StakedAgentServiceInstance = PredictTraderService;
export type AgentConfig = {
  name: string;
  evmHomeChainId: EvmChainId;
  middlewareHomeChainId: MiddlewareChain;
  requiresAgentSafesOn: EvmChainId[];
  agentSafeFundingRequirements: Record<string, number>;
  requiresMasterSafesOn: EvmChainId[];
  serviceApi: typeof PredictTraderService;
  displayName: string;
  description: string;
  operatingThresholds: {
    [owner: string | WalletOwnerType]: {
      [walletType: string | WalletOwnerType]: {
        [tokenSymbol: string | TokenSymbol]: number;
      };
    };
  };
};
