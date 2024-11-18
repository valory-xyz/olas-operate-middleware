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

export type MasterEoa = {
  address: Address;
  type: WalletType.EOA;
  owner: WalletOwner;
};

export type MasterSafe = Omit<MasterEoa, 'type'> & {
  type: WalletType.Safe;
  chainId: ChainId;
};

export type MasterWallet = MasterEoa | MasterSafe;

export type AgentEoa = {
  address: Address;
  type: WalletType.EOA;
  owner: WalletOwner.Agent;
};

export type AgentSafe = Omit<AgentEoa, 'type'> & {
  type: WalletType.Safe;
  chainId: ChainId;
};

export type AgentWallet = AgentEoa | AgentSafe;

export type Wallet = MasterWallet | AgentWallet;

export type MasterWallets = MasterWallet[];
export type AgentWallets = AgentWallet[];

export type Wallets = Wallet[];
