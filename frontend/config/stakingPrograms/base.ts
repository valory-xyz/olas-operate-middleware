import { Contract as MulticallContract } from 'ethers-multicall';

import { STAKING_TOKEN_PROXY_ABI } from '@/abis/stakingTokenProxy';
import { AgentType } from '@/enums/Agent';
import { EvmChainId } from '@/enums/Chain';
import { StakingProgramId } from '@/enums/StakingProgram';
import { TokenSymbol } from '@/enums/Token';
import { Address } from '@/types/Address';

import { ACTIVITY_CHECKERS, ActivityCheckerType } from '../activityCheckers';
import { StakingProgramMap } from '.';

export const BASE_STAKING_PROGRAMS_CONTRACT_ADDRESSES: Record<string, Address> =
  {
    [StakingProgramId.MemeBaseAlpha2]:
      '0xc653622FD75026a020995a1d8c8651316cBBc4dA',
  };

export const BASE_STAKING_PROGRAMS: StakingProgramMap = {
  [StakingProgramId.MemeBaseAlpha2]: {
    chainId: EvmChainId.Base,
    name: 'MemeBase Alpha',
    agentsSupported: [AgentType.Memeooorr],
    stakingRequirements: {
      [TokenSymbol.OLAS]: 100,
    },
    activityChecker:
      ACTIVITY_CHECKERS[EvmChainId.Base][
        ActivityCheckerType.MemeActivityChecker
      ],
    contract: new MulticallContract(
      BASE_STAKING_PROGRAMS_CONTRACT_ADDRESSES[StakingProgramId.MemeBaseAlpha2],
      STAKING_TOKEN_PROXY_ABI,
    ),
  },
};
