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
    [StakingProgramId.ModiusOptimusAlpha]:
      '0x5fc25f50e96857373c64dc0edb1abcbed4587e91',
  };

export const MODE_STAKING_PROGRAMS: StakingProgramMap = {
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
  [StakingProgramId.ModiusOptimusAlpha]: {
    chainId: EvmChainId.Mode,
    name: 'Optimus Alpha',
    agentsSupported: [AgentType.Modius],
    stakingRequirements: {
      [TokenSymbol.OLAS]: 40,
    },
    activityChecker:
      ACTIVITY_CHECKERS[EvmChainId.Mode][ActivityCheckerType.Staking],
    contract: new MulticallContract(
      MODE_STAKING_PROGRAMS_CONTRACT_ADDRESSES[
        StakingProgramId.ModiusOptimusAlpha
      ],
      STAKING_TOKEN_PROXY_ABI,
    ),
  },
};
