/**
 * Chain configurations
 * - add new chains to the CHAIN_CONFIGS object
 */
import { MiddlewareChain as MiddlewareChainId } from '@/client';
import { EvmChainId } from '@/enums/Chain';
import { TokenSymbol } from '@/enums/Token';

type HttpUrl = `http${'s' | ''}://${string}`;

type ChainConfig = {
  name: string;
  currency: string;
  chainId: number;
  middlewareChain: MiddlewareChainId;
  rpc: HttpUrl;
};

export const GNOSIS_CHAIN_CONFIG: ChainConfig = {
  chainId: EvmChainId.Gnosis,
  name: 'Gnosis',
  currency: TokenSymbol.XDAI,
  middlewareChain: MiddlewareChainId.GNOSIS,
  rpc: process.env.GNOSIS_RPC as HttpUrl,
};

export const OPTIMISM_CHAIN_CONFIG: ChainConfig = {
  chainId: EvmChainId.Optimism,
  name: 'Optimism',
  currency: TokenSymbol.ETH,
  middlewareChain: MiddlewareChainId.OPTIMISM,
  rpc: process.env.OPTIMISM_RPC as HttpUrl,
};

export const BASE_CHAIN_CONFIG: ChainConfig = {
  chainId: EvmChainId.Base,
  name: 'Base',
  currency: TokenSymbol.ETH,
  middlewareChain: MiddlewareChainId.BASE,
  rpc: process.env.BASE_RPC as HttpUrl,
};

export const ETHEREUM_CHAIN_CONFIG: ChainConfig = {
  chainId: EvmChainId.Ethereum,
  name: 'Ethereum',
  currency: TokenSymbol.ETH,
  middlewareChain: MiddlewareChainId.ETHEREUM,
  rpc: process.env.GNOSIS_RPC as HttpUrl,
};

export const CHAIN_CONFIG: {
  [chainId: number]: ChainConfig;
} = {
  [EvmChainId.Base]: BASE_CHAIN_CONFIG,
  [EvmChainId.Ethereum]: ETHEREUM_CHAIN_CONFIG,
  [EvmChainId.Gnosis]: GNOSIS_CHAIN_CONFIG,
  [EvmChainId.Optimism]: OPTIMISM_CHAIN_CONFIG,
} as const;
