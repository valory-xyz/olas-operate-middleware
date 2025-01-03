import { MiddlewareChain } from '@/client';
import {
  MEMEOOORR_BASE_TEMPLATE,
  PREDICT_AGENT_TEMPLATE,
} from '@/constants/serviceTemplates';
import { AgentType } from '@/enums/Agent';
import { EvmChainId } from '@/enums/Chain';
import { TokenSymbol } from '@/enums/Token';
import { WalletOwnerType, WalletType } from '@/enums/Wallet';
import { MemeooorBaseService } from '@/service/agents/Memeooor';
import { PredictTraderService } from '@/service/agents/PredictTrader';
// import { OptimusService } from '@/service/agents/Optimus';
import { AgentConfig } from '@/types/Agent';
import { formatEther } from '@/utils/numberFormatters';

// TODO: complete this config
// TODO: add funding requirements

const traderFundRequirements =
  PREDICT_AGENT_TEMPLATE.configurations[MiddlewareChain.GNOSIS]
    .fund_requirements;

const memeooorrRequirements =
  MEMEOOORR_BASE_TEMPLATE.configurations[MiddlewareChain.GNOSIS]
    .fund_requirements;

export const AGENT_CONFIG: {
  [key in AgentType]: AgentConfig;
} = {
  [AgentType.PredictTrader]: {
    name: 'Predict Trader',
    evmHomeChainId: EvmChainId.Gnosis,
    middlewareHomeChainId: MiddlewareChain.GNOSIS,
    requiresAgentSafesOn: [EvmChainId.Gnosis],
    operatingThresholds: {
      [WalletOwnerType.Master]: {
        [WalletType.Safe]: {
          [TokenSymbol.XDAI]: Number(
            formatEther(
              `${traderFundRequirements.agent + traderFundRequirements.safe}`,
            ),
          ),
        },
        [WalletType.EOA]: {
          [TokenSymbol.XDAI]: 0.1, // TODO: should come from the template
        },
      },
      [WalletOwnerType.Agent]: {
        [WalletType.Safe]: {
          [TokenSymbol.XDAI]: Number(formatEther(traderFundRequirements.agent)),
        },
        [WalletType.EOA]: {
          [TokenSymbol.XDAI]: 0.1, // TODO: should come from the template
        },
      },
    },
    requiresMasterSafesOn: [EvmChainId.Gnosis],
    serviceApi: PredictTraderService,
    displayName: 'Prediction agent',
    description: 'Participates in prediction markets.',
  },
  [AgentType.Memeooorr]: {
    name: 'Agents.fun agent',
    evmHomeChainId: EvmChainId.Base,
    middlewareHomeChainId: MiddlewareChain.BASE,
    requiresAgentSafesOn: [EvmChainId.Base],
    operatingThresholds: {
      [WalletOwnerType.Master]: {
        [WalletType.Safe]: {
          [TokenSymbol.ETH]: Number(formatEther(memeooorrRequirements.safe)),
        },
        [WalletType.EOA]: {
          [TokenSymbol.ETH]: 0.0125, // TODO: should come from the template
        },
      },
      [WalletOwnerType.Agent]: {
        [WalletType.Safe]: {
          [TokenSymbol.ETH]: Number(formatEther(memeooorrRequirements.agent)),
        },
        [WalletType.EOA]: {
          [TokenSymbol.ETH]: 0.00625, // TODO: should come from the template
        },
      },
    },
    requiresMasterSafesOn: [EvmChainId.Base],
    serviceApi: MemeooorBaseService,
    displayName: 'Agents.fun agent',
    description:
      'Autonomously post to Twitter, create and trade memecoins, and interact with other agents.',
  },
} as const;
