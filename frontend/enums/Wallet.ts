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

export type AgentEoa = {
  address: Address;
  type: WalletType.EOA;
  owner: WalletOwner.Agent;
};

export type AgentSafe = Omit<AgentEoa, 'type'> & {
  type: WalletType.Safe;
  chainId: ChainId;
};

export type MasterWallets = (MasterEoa | MasterSafe)[];
export type AgentWallets = (AgentEoa | AgentSafe)[];
