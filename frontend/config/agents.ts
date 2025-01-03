import { ethers } from 'ethers';
import { formatUnits } from 'ethers/lib/utils';

import { MiddlewareChain } from '@/client';
import {
  MEMEOOORR_BASE_TEMPLATE,
  MODIUS_BASE_TEMPLATE,
  PREDICT_AGENT_TEMPLATE,
} from '@/constants/serviceTemplates';
import { AgentType } from '@/enums/Agent';
import { EvmChainId } from '@/enums/Chain';
import { TokenSymbol } from '@/enums/Token';
import { WalletOwnerType, WalletType } from '@/enums/Wallet';
import { MemeooorBaseService } from '@/service/agents/Memeooor';
import { ModiusService } from '@/service/agents/Modius';
import { PredictTraderService } from '@/service/agents/PredictTrader';
import { AgentConfig } from '@/types/Agent';
import { formatEther } from '@/utils/numberFormatters';

import { CHAIN_CONFIG } from './chains';
import { MODE_TOKEN_CONFIG } from './tokens';

const traderFundRequirements =
  PREDICT_AGENT_TEMPLATE.configurations[MiddlewareChain.GNOSIS]
    .fund_requirements;

const memeooorrRequirements =
  MEMEOOORR_BASE_TEMPLATE.configurations[MiddlewareChain.BASE]
    .fund_requirements;

const modiusFundRequirements =
  MODIUS_BASE_TEMPLATE?.configurations[MiddlewareChain.MODE].fund_requirements;

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
              `${
                traderFundRequirements?.[ethers.constants.AddressZero].agent +
                traderFundRequirements?.[ethers.constants.AddressZero].safe
              }`,
            ),
          ),
        },
        [WalletType.EOA]: {
          [TokenSymbol.XDAI]: 0.1, // TODO: should come from the template
        },
      },
      [WalletOwnerType.Agent]: {
        [WalletType.Safe]: {
          [TokenSymbol.XDAI]: Number(
            formatEther(`${traderFundRequirements.agent}`),
          ),
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
    eoaFunding: {
      [EvmChainId.Gnosis]: {
        chainConfig: CHAIN_CONFIG[EvmChainId.Gnosis],
      },
    },
    isAgentEnabled: true,
  },
  [AgentType.Memeooorr]: {
    name: 'Agents.fun agent',
    evmHomeChainId: EvmChainId.Base,
    middlewareHomeChainId: MiddlewareChain.BASE,
    requiresAgentSafesOn: [EvmChainId.Base],
    operatingThresholds: {
      [WalletOwnerType.Master]: {
        [WalletType.Safe]: {
          [TokenSymbol.ETH]: Number(
            formatEther(`${memeooorrRequirements.safe}`),
          ),
        },
        [WalletType.EOA]: {
          [TokenSymbol.ETH]: 0.0125, // TODO: should come from the template
        },
      },
      [WalletOwnerType.Agent]: {
        [WalletType.Safe]: {
          [TokenSymbol.ETH]: Number(
            formatEther(`${memeooorrRequirements.agent}`),
          ),
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
    eoaFunding: {
      [EvmChainId.Base]: {
        chainConfig: CHAIN_CONFIG[EvmChainId.Base],
      },
    },
    isAgentEnabled: true,
  },
  [AgentType.Modius]: {
    name: 'Modius agent',
    evmHomeChainId: EvmChainId.Mode,
    middlewareHomeChainId: MiddlewareChain.MODE,
    requiresAgentSafesOn: [EvmChainId.Mode],
    additionalRequirements: {
      [EvmChainId.Mode]: {
        [TokenSymbol.USDC]: Number(
          formatUnits(
            modiusFundRequirements?.[
              MODE_TOKEN_CONFIG[TokenSymbol.USDC].address as string
            ]?.safe ?? 0,
            MODE_TOKEN_CONFIG[TokenSymbol.USDC].decimals,
          ),
        ),
      },
    },
    operatingThresholds: {
      [WalletOwnerType.Master]: {
        [WalletType.EOA]: {
          [TokenSymbol.ETH]: 0.0002,
        },
        [WalletType.Safe]: {
          [TokenSymbol.ETH]: 0.0055,
        },
      },
      [WalletOwnerType.Agent]: {
        [WalletType.EOA]: {
          [TokenSymbol.ETH]: 0.0005,
        },
        [WalletType.Safe]: {
          [TokenSymbol.ETH]: 0.005,
        },
      },
    },
    requiresMasterSafesOn: [EvmChainId.Mode],
    serviceApi: ModiusService,
    displayName: 'Modius agent',
    description:
      'Invests crypto assets on your behalf and grows your portfolio.',
    eoaFunding: {
      [EvmChainId.Mode]: {
        chainConfig: CHAIN_CONFIG[EvmChainId.Mode],
      },
    },
    isAgentEnabled: false,
  },
};
