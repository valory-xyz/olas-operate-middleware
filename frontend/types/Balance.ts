import { EvmChainId } from '@/enums/Chain';
import { TokenSymbol } from '@/enums/Token';
import { Address } from '@/types/Address';

export type WalletBalance = {
  walletAddress: Address;
  evmChainId: EvmChainId;
  symbol: TokenSymbol;
  isNative: boolean;
  balance: number;
  isWrappedToken?: boolean;
};

export type CrossChainStakedBalances = Array<{
  serviceId: string;
  evmChainId: number;
  olasBondBalance: number;
  olasDepositBalance: number;
  walletAddress: Address;
}>;
