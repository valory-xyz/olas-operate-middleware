import { PROVIDERS } from '@/constants/providers';
import { EvmChainId } from '@/enums/Chain';

import { AGENT_CONFIG } from './agents';

const allAgentConfig = Object.values(AGENT_CONFIG);

/**
 * Provider entries for enabled agents.
 * @example
 * [{
 *    key: '1',
 *    value: { provider: JsonRpcProvider, multicallProvider: MulticallProvider }
 * }]
 */
export const providers = Object.entries(PROVIDERS).filter(([key]) => {
  const evmChainId = +key as EvmChainId;
  const currentAgentConfig = allAgentConfig.find(
    (agentConfig) => agentConfig.evmHomeChainId === evmChainId,
  );

  return !!currentAgentConfig?.isAgentEnabled;
});
