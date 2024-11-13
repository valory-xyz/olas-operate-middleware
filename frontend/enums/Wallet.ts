import { Address } from '@/types/Address';

import { ChainId } from './Chain';

export enum WalletType {
  Safe = 'multisig',
  EOA = 'eoa',
}

export enum WalletOwner {
  Master = 'master', // user
  Agent = 'agent',
}

export type EoaWallet = {
  address: Address;
  type: WalletType.EOA;
  owner: WalletOwner;
};

export type SafeWallet = {
  address: Address;
  type: WalletType.Safe;
  owner: WalletOwner;
  chainId: ChainId;
};
