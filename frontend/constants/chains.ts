import { MiddlewareChain } from '@/client';

export const CHAINS: {
  [chain: string]: {
    name: string;
    currency: string;
    chainId: number;
    middlewareChain: MiddlewareChain;
  };
} = {
  GNOSIS: {
    name: 'Gnosis',
    currency: 'XDAI',
    chainId: 100,
    middlewareChain: MiddlewareChain.GNOSIS,
  },
  OPTIMISM: {
    name: 'Optimism',
    currency: 'ETH',
    chainId: 10,
    middlewareChain: MiddlewareChain.OPTIMISM,
  },
  BASE: {
    name: 'Base',
    currency: 'ETH',
    chainId: 8453,
    middlewareChain: MiddlewareChain.BASE,
  },
  ETHEREUM: {
    name: 'Ethereum',
    currency: 'ETH',
    chainId: 1,
    middlewareChain: MiddlewareChain.ETHEREUM,
  },
};
