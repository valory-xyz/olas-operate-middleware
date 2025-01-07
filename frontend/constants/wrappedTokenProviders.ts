import { getAddress } from 'ethers/lib/utils';
import { Contract as MulticallContract } from 'ethers-multicall';

import { EvmChainId } from '@/enums/Chain';

const wrappedXdaiProvider = new MulticallContract(
  getAddress('0xe91d153e0b41518a2ce8dd3d7944fa863463a97d'),
  ['function balanceOf(address owner) view returns (uint256)'],
);

export const WRAPPED_TOKEN_PROVIDERS: {
  [key in EvmChainId]: MulticallContract | null;
} = {
  [EvmChainId.Ethereum]: null,
  [EvmChainId.Optimism]: null,
  [EvmChainId.Gnosis]: wrappedXdaiProvider,
  [EvmChainId.Base]: null,
  [EvmChainId.Mode]: null,
};
