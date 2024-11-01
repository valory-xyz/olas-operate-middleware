import { ethers } from 'ethers';
import { Provider as MulticallProvider } from 'ethers-multicall';

import { CHAINS } from './chains';

export const gnosisProvider = new ethers.providers.JsonRpcProvider(
  process.env.RPC,
  {
    chainId: CHAINS.GNOSIS.chainId,
    name: CHAINS.GNOSIS.name,
  },
);

export const gnosisMulticallProvider = new MulticallProvider(
  gnosisProvider,
  CHAINS.GNOSIS.chainId,
);

export const optimismProvider = new ethers.providers.JsonRpcProvider(
  process.env.OPTIMISM_RPC,
  {
    chainId: CHAINS.OPTIMISM.chainId,
    name: CHAINS.OPTIMISM.name,
  },
);

export const optimismMulticallProvider = new MulticallProvider(
  optimismProvider,
  CHAINS.OPTIMISM.chainId,
);

export const ethereumProvider = new ethers.providers.JsonRpcProvider(
  process.env.ETHEREUM_RPC,
  {
    chainId: CHAINS.ETHEREUM.chainId,
    name: CHAINS.ETHEREUM.name,
  },
);

export const ethereumMulticallProvider = new MulticallProvider(
  ethereumProvider,
  CHAINS.ETHEREUM.chainId,
);

export const baseProvider = new ethers.providers.JsonRpcProvider(
  process.env.BASE_RPC,
  {
    chainId: CHAINS.BASE.chainId,
    name: CHAINS.BASE.name,
  },
);

export const baseMulticallProvider = new MulticallProvider(
  baseProvider,
  CHAINS.BASE.chainId,
);
