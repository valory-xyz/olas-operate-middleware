import { MiddlewareChain } from '@/client';
import { ChainId } from '@/enums/Chain';

/**
 * Converts middleware chain enums to chain ids
 * @param chain
 * @returns ChainId
 * @throws Error
 */
export const convertMiddlewareChainToChainId = (
  chain: MiddlewareChain | string,
): ChainId => {
  switch (chain) {
    case MiddlewareChain.ETHEREUM:
      return ChainId.Ethereum;
    case MiddlewareChain.OPTIMISM:
      return ChainId.Optimism;
    case MiddlewareChain.GNOSIS:
      return ChainId.Gnosis;
    case MiddlewareChain.BASE:
      return ChainId.Base;
  }
  throw new Error(`Invalid middleware chain enum: ${chain}`);
};

export const convertChainIdToMiddlewareChain = (chainId: ChainId | number) => {
  switch (chainId) {
    case ChainId.Ethereum:
      return MiddlewareChain.ETHEREUM;
    case ChainId.Optimism:
      return MiddlewareChain.OPTIMISM;
    case ChainId.Gnosis:
      return MiddlewareChain.GNOSIS;
    case ChainId.Base:
      return MiddlewareChain.BASE;
  }
  throw new Error(`Invalid chain id: ${chainId}`);
};
