import { useMemo } from 'react';

import { Address } from '@/types/Address';
import { Service } from '@/types/Service';

/**
 * Hook for interacting with a single service.
 */
export const useService = (service: Service) => {
  // ChainIds used by the service
  const chainIdsUsed = useMemo<number[]>(() => {
    return Object.keys(service.chain_configs).map(Number);
  }, [service.chain_configs]);

  const addresses = useMemo<{
    [chainId: number]: {
      master: {
        safe: Address;
        signer: Address;
      };
      agent: {
        safe: Address;
        signer: Address;
      };
    };
  }>(
    () =>
      chainIdsUsed.reduce((acc, chainId) => {
        const chainConfig = service.chain_configs[chainId];
        const master = {
          safe: chainConfig.master.safe,
          signer: chainConfig.master.signer,
        };
        const agent = {
          safe: chainConfig.agent.safe,
          signer: chainConfig.agent.signer,
        };

        return {
          ...acc,
          [chainId]: {
            master,
            agent,
          },
        };
      }, {}),
    [chainIdsUsed, service.chain_configs],
  );

  return {
    wallets,
  };
};
