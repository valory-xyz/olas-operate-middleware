import { ethers } from 'ethers';
import { Provider } from 'ethers-multicall';

export const provider = new ethers.providers.JsonRpcProvider(
  `${process.env.RPC}`,
  {
    name: 'Gnosis',
    chainId: 100,
  },
);

export const multicallProvider = new Provider(provider, 100);

multicallProvider.init();
