/**
 * Chain configurations
 * - add new chains to the CHAIN_CONFIGS object
 */
import { MiddlewareChain } from '@/client';

type HttpUrl = `http${'s' | ''}://${string}`;

type ChainConfig = {
  name: string;
  currency: string;
  chainId: number;
  middlewareChain: MiddlewareChain;
  rpc: HttpUrl;
};

export const GNOSIS_CHAIN_CONFIG: ChainConfig = {
  chainId: 100,
  name: 'Gnosis',
  currency: 'XDAI',
  middlewareChain: MiddlewareChain.GNOSIS,
  rpc: process.env.GNOSIS_RPC as HttpUrl,
};

export const OPTIMISM_CHAIN_CONFIG: ChainConfig = {
  chainId: 10,
  name: 'Optimism',
  currency: 'ETH',
  middlewareChain: MiddlewareChain.OPTIMISM,
  rpc: process.env.OPTIMISM_RPC as HttpUrl,
};

export const BASE_CHAIN_CONFIG: ChainConfig = {
  chainId: 8453,
  name: 'Base',
  currency: 'ETH',
  middlewareChain: MiddlewareChain.BASE,
  rpc: process.env.BASE_RPC as HttpUrl,
};

export const ETHEREUM_CHAIN_CONFIG: ChainConfig = {
  chainId: 1,
  name: 'Ethereum',
  currency: 'ETH',
  middlewareChain: MiddlewareChain.ETHEREUM,
  rpc: process.env.GNOSIS_RPC as HttpUrl,
};

export const CHAIN_CONFIG = {
  BASE: BASE_CHAIN_CONFIG,
  ETHEREUM: ETHEREUM_CHAIN_CONFIG,
  GNOSIS: GNOSIS_CHAIN_CONFIG,
  OPTIMISM: OPTIMISM_CHAIN_CONFIG,
} as const;
