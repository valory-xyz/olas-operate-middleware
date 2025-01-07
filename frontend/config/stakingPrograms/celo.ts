import { Contract as MulticallContract } from 'ethers-multicall';

import { STAKING_TOKEN_PROXY_ABI } from '@/abis/stakingTokenProxy';
import { AgentType } from '@/enums/Agent';
import { EvmChainId } from '@/enums/Chain';
import { StakingProgramId } from '@/enums/StakingProgram';
import { TokenSymbol } from '@/enums/Token';
import { Address } from '@/types/Address';

import { ACTIVITY_CHECKERS, ActivityCheckerType } from '../activityCheckers';
import { StakingProgramMap } from '.';

export const CELO_STAKING_PROGRAMS_CONTRACT_ADDRESSES: Record<string, Address> =
  {
    [StakingProgramId.MemeCeloAlpha2]:
      '0xc653622FD75026a020995a1d8c8651316cBBc4dA', // TODO: celo
  };

export const CELO_STAKING_PROGRAMS: StakingProgramMap = {
  [StakingProgramId.MemeCeloAlpha2]: {
    chainId: EvmChainId.Celo,
    name: 'MemeCelo Alpha II',
    agentsSupported: [AgentType.AgentsFunCelo],
    stakingRequirements: {
      [TokenSymbol.OLAS]: 100, // TODO: celo
    },
    activityChecker:
      ACTIVITY_CHECKERS[EvmChainId.Celo][
        ActivityCheckerType.MemeActivityChecker // TODO: celo
      ],
    contract: new MulticallContract(
      CELO_STAKING_PROGRAMS_CONTRACT_ADDRESSES[StakingProgramId.MemeCeloAlpha2],
      STAKING_TOKEN_PROXY_ABI,
    ),
  },
};
