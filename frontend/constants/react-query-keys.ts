export const REACT_QUERY_KEYS = {
  SERVICES: ['services'] as const,
  SERVICE_STATUS: (uuid: string) => ['serviceStatus', uuid] as const,
} as const;
