import { MiddlewareChain } from '@/client';
import { ChainConfig } from '@/config/chains';
import { EvmChainId } from '@/enums/Chain';
import { TokenSymbol } from '@/enums/Token';
import { WalletOwnerType, WalletType } from '@/enums/Wallet';
import { PredictTraderService } from '@/service/agents/PredictTrader';

export type AgentSupportedEvmChainIds = EvmChainId.Base | EvmChainId.Gnosis;

export type AgentConfig = {
  name: string;
  evmHomeChainId: EvmChainId;
  middlewareHomeChainId: MiddlewareChain;
  requiresAgentSafesOn: EvmChainId[];
  requiresMasterSafesOn: EvmChainId[];
  serviceApi: typeof PredictTraderService;
  displayName: string;
  description: string;
  eoaFunding: Partial<{
    [chainId in AgentSupportedEvmChainIds]: {
      chainConfig: ChainConfig;
    };
  }>;
  /**
   * The operating thresholds for the agent to continue running (after "initial funding").
   * (For example, the agent may require a minimum balance of 0.1 xDAI to continue running)
   */
  operatingThresholds: {
    [owner in WalletOwnerType.Agent | WalletOwnerType.Master]: {
      [walletType in WalletType.EOA | WalletType.Safe]: {
        [tokenSymbol: string | TokenSymbol]: number;
      };
    };
  };
};

export type AgentHealthCheck = {
  seconds_since_last_transition: number;
  is_tm_healthy: boolean;
  period: number;
  reset_pause_duration: number;
  is_transitioning_fast: boolean;
  rounds: string[];
  rounds_info?: Record<
    string,
    {
      name: string;
      description: string;
      transitions: Record<string, string>;
    }
  >;
};
