export const CHAINS: {
  [chain: string]: {
    currency: string;
    chainId: number;
  };
} = {
  GNOSIS: { currency: 'XDAI', chainId: 100 },
  OPTIMISM: { currency: 'ETH', chainId: 10 },
};
