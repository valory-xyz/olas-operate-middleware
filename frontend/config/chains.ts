/**
 * Chain configurations
 * - add new chains to the CHAIN_CONFIGS object
 */
import { MiddlewareChain } from '@/client';
import { ChainId } from '@/enums/Chain';
import { TokenSymbol } from '@/enums/Token';

type HttpUrl = `http${'s' | ''}://${string}`;

type ChainConfig = {
  name: string;
  currency: TokenSymbol;
  chainId: ChainId;
  middlewareChain: MiddlewareChain;
  rpc: HttpUrl;
};

export const GNOSIS_CHAIN_CONFIG: ChainConfig = {
  chainId: ChainId.Gnosis,
  name: 'Gnosis',
  currency: TokenSymbol.XDAI,
  middlewareChain: MiddlewareChain.GNOSIS,
  rpc: process.env.GNOSIS_RPC as HttpUrl,
};

export const OPTIMISM_CHAIN_CONFIG: ChainConfig = {
  chainId: ChainId.Optimism,
  name: 'Optimism',
  currency: TokenSymbol.ETH,
  middlewareChain: MiddlewareChain.OPTIMISM,
  rpc: process.env.OPTIMISM_RPC as HttpUrl,
};

export const BASE_CHAIN_CONFIG: ChainConfig = {
  chainId: ChainId.Base,
  name: 'Base',
  currency: TokenSymbol.ETH,
  middlewareChain: MiddlewareChain.BASE,
  rpc: process.env.BASE_RPC as HttpUrl,
};

export const ETHEREUM_CHAIN_CONFIG: ChainConfig = {
  chainId: ChainId.Ethereum,
  name: 'Ethereum',
  currency: TokenSymbol.ETH,
  middlewareChain: MiddlewareChain.ETHEREUM,
  rpc: process.env.GNOSIS_RPC as HttpUrl,
};

export const CHAIN_CONFIG = {
  [ChainId.Base]: BASE_CHAIN_CONFIG,
  [ChainId.Ethereum]: ETHEREUM_CHAIN_CONFIG,
  [ChainId.Gnosis]: GNOSIS_CHAIN_CONFIG,
  [ChainId.Optimism]: OPTIMISM_CHAIN_CONFIG,
} as const;
