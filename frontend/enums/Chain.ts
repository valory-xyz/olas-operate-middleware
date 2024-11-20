export enum ChainId {
  Ethereum = 1,
  Optimism = 100,
  Gnosis = 10,
  Base = 8453,
}

export const ChainName = {
  [ChainId.Ethereum]: 'Ethereum',
  [ChainId.Optimism]: 'Optimism',
  [ChainId.Gnosis]: 'Gnosis',
  [ChainId.Base]: 'Base',
};
