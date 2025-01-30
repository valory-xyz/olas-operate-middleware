import { Contract as MulticallContract } from 'ethers-multicall';

import { STAKING_TOKEN_PROXY_ABI } from '@/abis/stakingTokenProxy';
import { AgentType } from '@/enums/Agent';
import { EvmChainId } from '@/enums/Chain';
import { StakingProgramId } from '@/enums/StakingProgram';
import { TokenSymbol } from '@/enums/Token';
import { Address } from '@/types/Address';

import { ACTIVITY_CHECKERS, ActivityCheckerType } from '../activityCheckers';
import { StakingProgramMap } from '.';

export const MODE_STAKING_PROGRAMS_CONTRACT_ADDRESSES: Record<string, Address> =
  {
    [StakingProgramId.ModiusAlpha]:
      '0x534C0A05B6d4d28d5f3630D6D74857B253cf8332',
    [StakingProgramId.OptimusAlpha]:
      '0x5fc25f50e96857373c64dc0edb1abcbed4587e91',
    [StakingProgramId.ModiusAlpha2]:
      '0xeC013E68FE4B5734643499887941eC197fd757D0',
    [StakingProgramId.ModiusAlpha3]:
      '0x9034D0413D122015710f1744A19eFb1d7c2CEB13',
    [StakingProgramId.ModiusAlpha4]:
      '0x8BcAdb2c291C159F9385964e5eD95a9887302862',
  };

export const MODE_STAKING_PROGRAMS: StakingProgramMap = {
  // modius alpha
  [StakingProgramId.ModiusAlpha]: {
    chainId: EvmChainId.Mode,
    name: 'Modius Alpha',
    agentsSupported: [AgentType.Modius],
    stakingRequirements: {
      [TokenSymbol.OLAS]: 40,
    },
    activityChecker:
      ACTIVITY_CHECKERS[EvmChainId.Mode][ActivityCheckerType.Staking],
    contract: new MulticallContract(
      MODE_STAKING_PROGRAMS_CONTRACT_ADDRESSES[StakingProgramId.ModiusAlpha],
      STAKING_TOKEN_PROXY_ABI,
    ),
  },
  [StakingProgramId.ModiusAlpha2]: {
    chainId: EvmChainId.Mode,
    name: 'Modius Alpha 2',
    agentsSupported: [AgentType.Modius],
    stakingRequirements: {
      [TokenSymbol.OLAS]: 100,
    },
    activityChecker:
      ACTIVITY_CHECKERS[EvmChainId.Mode][ActivityCheckerType.Staking],
    contract: new MulticallContract(
      MODE_STAKING_PROGRAMS_CONTRACT_ADDRESSES[StakingProgramId.ModiusAlpha2],
      STAKING_TOKEN_PROXY_ABI,
    ),
  },
  [StakingProgramId.ModiusAlpha3]: {
    chainId: EvmChainId.Mode,
    name: 'Modius Alpha 3',
    agentsSupported: [AgentType.Modius],
    stakingRequirements: {
      [TokenSymbol.OLAS]: 1000,
    },
    activityChecker:
      ACTIVITY_CHECKERS[EvmChainId.Mode][ActivityCheckerType.Staking],
    contract: new MulticallContract(
      MODE_STAKING_PROGRAMS_CONTRACT_ADDRESSES[StakingProgramId.ModiusAlpha3],
      STAKING_TOKEN_PROXY_ABI,
    ),
  },
  [StakingProgramId.ModiusAlpha4]: {
    chainId: EvmChainId.Mode,
    name: 'Modius Alpha 4',
    agentsSupported: [AgentType.Modius],
    stakingRequirements: {
      [TokenSymbol.OLAS]: 5000,
    },
    activityChecker:
      ACTIVITY_CHECKERS[EvmChainId.Mode][ActivityCheckerType.Staking],
    contract: new MulticallContract(
      MODE_STAKING_PROGRAMS_CONTRACT_ADDRESSES[StakingProgramId.ModiusAlpha4],
      STAKING_TOKEN_PROXY_ABI,
    ),
  },
  //optimus alpha
  [StakingProgramId.OptimusAlpha]: {
    chainId: EvmChainId.Mode,
    name: 'Optimus Alpha',
    agentsSupported: [AgentType.Modius],
    stakingRequirements: {
      [TokenSymbol.OLAS]: 40,
    },
    activityChecker:
      ACTIVITY_CHECKERS[EvmChainId.Mode][ActivityCheckerType.Staking],
    contract: new MulticallContract(
      MODE_STAKING_PROGRAMS_CONTRACT_ADDRESSES[StakingProgramId.OptimusAlpha],
      STAKING_TOKEN_PROXY_ABI,
    ),
  },
};
