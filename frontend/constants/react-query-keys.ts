export const REACT_QUERY_KEYS = {
  // service provider
  SERVICES_KEY: ['services'] as const,
  SERVICE_DEPLOYMENT_STATUS_KEY: (serviceConfigId: string) =>
    ['serviceStatus', serviceConfigId] as const,
  // wallet provider
  WALLETS_KEY: ['wallets'] as const,
} as const;
