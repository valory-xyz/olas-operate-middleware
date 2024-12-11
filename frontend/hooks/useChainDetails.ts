import { CHAIN_CONFIG } from '@/config/chains';
import { EvmChainId } from '@/enums/Chain';

export const useChainDetails = (chainId: EvmChainId) => {
  if (!chainId) throw new Error('Chain ID is required');

  const details = CHAIN_CONFIG[chainId];
  if (!details) {
    throw new Error(`Chain details not found for chain ID: ${chainId}`);
  }

  return {
    name: details.name,
    symbol: details.nativeToken.symbol,
  };
};
