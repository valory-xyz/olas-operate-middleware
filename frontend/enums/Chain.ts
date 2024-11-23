export enum EvmChainId {
  Ethereum = 1,
  Optimism = 100,
  Gnosis = 10,
  Base = 8453,
}

export const EvmChainName = {
  [EvmChainId.Ethereum]: 'Ethereum',
  [EvmChainId.Optimism]: 'Optimism',
  [EvmChainId.Gnosis]: 'Gnosis',
  [EvmChainId.Base]: 'Base',
};
