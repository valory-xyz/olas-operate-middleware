export enum EvmChainId {
  Gnosis = 100,
  Base = 8453,
  Mode = 34443,
  Celo = 42220,
}

export const EvmChainName = {
  [EvmChainId.Gnosis]: 'Gnosis',
  [EvmChainId.Base]: 'Base',
  [EvmChainId.Mode]: 'Mode',
  [EvmChainId.Celo]: 'Celo',
};

export enum AllEvmChainId {
  Gnosis = EvmChainId.Gnosis,
  Base = EvmChainId.Base,
  Mode = EvmChainId.Mode,
  Celo = EvmChainId.Celo,
  Ethereum = 1,
  Optimism = 10,
}
