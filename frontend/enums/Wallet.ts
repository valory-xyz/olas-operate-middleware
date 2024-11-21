import { Address } from '@/types/Address';

import { ChainId } from './Chain';

export enum WalletType {
  Safe = 'multisig',
  EOA = 'eoa',
}
export enum WalletOwnerType {
  Master = 'master', // user
  Agent = 'agent',
}

export type Eoa = {
  address: Address;
  type: WalletType.EOA;
};

export type Safe = {
  address: Address;
  type: WalletType.Safe;
  chainId: ChainId;
};

export type MasterEoa = Eoa & {
  owner: WalletOwnerType.Master;
};

export type AgentEoa = Eoa & {
  owner: WalletOwnerType.Agent;
};

export type MasterSafe = Safe & {
  owner: WalletOwnerType.Master;
};

export type AgentSafe = Safe & {
  owner: WalletOwnerType.Agent;
};

export type MasterWallet = MasterEoa | MasterSafe;
export type AgentWallet = AgentEoa | AgentSafe;

export type MasterWallets = MasterWallet[];
export type AgentWallets = AgentWallet[];

export type Wallet = MasterWallet | AgentWallet;
export type Wallets = Wallet[];
