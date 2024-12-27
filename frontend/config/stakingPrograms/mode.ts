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
    [StakingProgramId.OptimusAlpha]:
      '0x5fc25f50E96857373C64dC0eDb1AbCBEd4587e91',
  };

export const MODE_STAKING_PROGRAMS: StakingProgramMap = {
  [StakingProgramId.OptimusAlpha]: {
    chainId: EvmChainId.Mode,
    name: 'Modius Alpha',
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
