import { setMulticallAddress } from 'ethers-multicall';

import { MULTICALL3_ABI } from '@/abis/multicall3';
import { SERVICE_REGISTRY_L2_ABI } from '@/abis/serviceRegistryL2';
import { SERVICE_REGISTRY_TOKEN_UTILITY_ABI } from '@/abis/serviceRegistryTokenUtility';
import { STAKING_TOKEN_PROXY_ABI } from '@/abis/stakingTokenProxy';
import { ContractType } from '@/enums/Contract';
import { StakingProgramId } from '@/enums/StakingProgram';
import { Abi } from '@/types/ABI';
import { Address } from '@/types/Address';

import { CHAIN_CONFIG } from './chains';

export type ContractParams = {
  address: Address;
  abi: Abi;
  type?: ContractType;
};

type ContractsConfig = {
  MULTICALL3: ContractParams;
  SERVICE_REGISTRY_L2: ContractParams;
  SERVICE_REGISTRY_TOKEN_UTILITY: ContractParams;
  STAKING_TOKEN_PROXYS: Partial<Record<StakingProgramId, ContractParams>>;
  MECHS?: {
    AGENT_MECH?: ContractParams;
    MECH_MARKETPLACE: ContractParams;
  };
  ACTIVITY_CHECKERS?: {
    AGENT_MECH_ACTIVITY?: ContractParams;
    MECH_MARKETPLACE_ACTIVITY?: ContractParams;
    STAKING_ACTIVITY?: ContractParams;
  };
};

export const OPTIMISM_CONTRACT_CONFIG: ContractsConfig = {
  MULTICALL3: {
    address: '0xcA11bde05977b3631167028862bE2a173976CA11',
    abi: MULTICALL3_ABI,
  },
  SERVICE_REGISTRY_L2: {
    address: '0x3d77596beb0f130a4415df3D2D8232B3d3D31e44',
    abi: SERVICE_REGISTRY_L2_ABI,
  },
  SERVICE_REGISTRY_TOKEN_UTILITY: {
    address: '0xBb7e1D6Cb6F243D6bdE81CE92a9f2aFF7Fbe7eac',
    abi: SERVICE_REGISTRY_TOKEN_UTILITY_ABI,
  },
  STAKING_TOKEN_PROXYS: {
    [StakingProgramId.OptimusAlpha]: {
      address: '0x88996bbdE7f982D93214881756840cE2c77C4992',
      abi: STAKING_TOKEN_PROXY_ABI,
    },
  },
  MECHS: {
    MECH_MARKETPLACE: {
      address: '0x3d77596beb0f130a4415df3D2D8232B3d3D31e44',
      abi: STAKING_TOKEN_PROXY_ABI,
    },
  },
  ACTIVITY_CHECKERS: {
    STAKING_ACTIVITY: {
      address: '0x7Fd1F4b764fA41d19fe3f63C85d12bf64d2bbf68',
      abi: STAKING_TOKEN_PROXY_ABI,
    },
  },
};

export const GNOSIS_CONTRACT_CONFIG: ContractsConfig = {
  MULTICALL3: {
    address: '0xcA11bde05977b3631167028862bE2a173976CA11',
    abi: MULTICALL3_ABI,
  },
  SERVICE_REGISTRY_L2: {
    address: '0x9338b5153AE39BB89f50468E608eD9d764B755fD',
    abi: SERVICE_REGISTRY_L2_ABI,
  },
  SERVICE_REGISTRY_TOKEN_UTILITY: {
    address: '0xa45E64d13A30a51b91ae0eb182e88a40e9b18eD8',
    abi: SERVICE_REGISTRY_TOKEN_UTILITY_ABI,
  },
  STAKING_TOKEN_PROXYS: {
    [StakingProgramId.PearlAlpha]: {
      address: '0xEE9F19b5DF06c7E8Bfc7B28745dcf944C504198A',
      abi: STAKING_TOKEN_PROXY_ABI,
    },
    [StakingProgramId.PearlBeta]: {
      address: '0xeF44Fb0842DDeF59D37f85D61A1eF492bbA6135d',
      abi: STAKING_TOKEN_PROXY_ABI,
    },
    [StakingProgramId.PearlBeta2]: {
      address: '0x1c2F82413666d2a3fD8bC337b0268e62dDF67434',
      abi: STAKING_TOKEN_PROXY_ABI,
    },
    [StakingProgramId.PearlBeta3]: {
      address: '0xBd59Ff0522aA773cB6074ce83cD1e4a05A457bc1',
      abi: STAKING_TOKEN_PROXY_ABI,
    },
    [StakingProgramId.PearlBeta4]: {
      address: '0x3052451e1eAee78e62E169AfdF6288F8791F2918',
      abi: STAKING_TOKEN_PROXY_ABI,
    },
    [StakingProgramId.PearlBeta5]: {
      address: '0x4Abe376Fda28c2F43b84884E5f822eA775DeA9F4',
      abi: STAKING_TOKEN_PROXY_ABI,
    },
    [StakingProgramId.PearlBetaMechMarketplace]: {
      address: '0xDaF34eC46298b53a3d24CBCb431E84eBd23927dA',
      abi: STAKING_TOKEN_PROXY_ABI,
    },
  },
};

export const CONTRACT_CONFIG = {
  [CHAIN_CONFIG.GNOSIS.chainId]: GNOSIS_CONTRACT_CONFIG,
  [CHAIN_CONFIG.OPTIMISM.chainId]: OPTIMISM_CONTRACT_CONFIG,
};

/**
 * Sets the multicall contract address for each chain
 * @warning Do not remove this, it is required for the multicall provider to work as package is not updated
 * @see https://github.com/cavanmflynn/ethers-multicall/blob/fb84bcc3763fe54834a35a44c34d610bafc87ce5/src/provider.ts#L35C1-L53C1
 * @note will use different multicall package in future
 */
Object.entries(CONTRACT_CONFIG).forEach(
  ([
    chainId,
    {
      MULTICALL3: { address: MULTICALL_CONTRACT_ADDRESS },
    },
  ]) => {
    setMulticallAddress(+chainId, MULTICALL_CONTRACT_ADDRESS);
  },
);
