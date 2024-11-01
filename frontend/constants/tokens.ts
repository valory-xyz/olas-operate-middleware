import { Address } from '@/types/Address';

import { CHAINS } from './chains';

export type TokenConfig = {
  [symbol: string]: {
    address: Address;
    decimals: number;
  };
};

export const TOKENS: {
  [chain: number]: TokenConfig;
} = {
  // [CHAINS.GNOSIS.chainId]: {
  //   OLAS: {
  //     address: '0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f',
  //     decimals: 18,
  //   },
  // },
  [CHAINS.OPTIMISM.chainId]: {
    OLAS: {
      address: '0xFC2E6e6BCbd49ccf3A5f029c79984372DcBFE527',
      decimals: 18,
    },
  },
  [CHAINS.ETHEREUM.chainId]: {
    OLAS: {
      address: '0x0001A500A6B18995B03f44bb040A5fFc28E45CB0',
      decimals: 18,
    },
    USDC: {
      address: '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
      decimals: 18,
    },
  },
  [CHAINS.BASE.chainId]: {
    OLAS: {
      address: '0x4B1a99467a284CC690e3237bc69105956816F762',
      decimals: 18,
    },
  },
};
