import { ethers } from 'ethers';
import { Provider } from 'ethers-multicall';

import { CHAINS } from './chains';

// export const gnosisProvider = new ethers.providers.StaticJsonRpcProvider(
//   process.env.RPC,
// );

// export const gnosisMulticallProvider = new Provider(
//   gnosisProvider,
//   CHAINS.GNOSIS.chainId,
// );

export const optimismProvider = new ethers.providers.StaticJsonRpcProvider(
  process.env.OPTIMISM_RPC,
);

export const optimismMulticallProvider = new Provider(
  optimismProvider,
  CHAINS.OPTIMISM.chainId,
);

export const ethereumProvider = new ethers.providers.StaticJsonRpcProvider(
  process.env.ETHEREUM_RPC,
);

export const ethereumMulticallProvider = new Provider(
  ethereumProvider,
  CHAINS.ETHEREUM.chainId,
);

export const baseProvider = new ethers.providers.StaticJsonRpcProvider(
  process.env.BASE_RPC,
);

export const baseMulticallProvider = new Provider(
  baseProvider,
  CHAINS.BASE.chainId,
);
