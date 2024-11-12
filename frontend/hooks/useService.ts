import { useMemo } from 'react';

import { MiddlewareDeploymentStatus } from '@/client';
import { Address } from '@/types/Address';

import { useServices } from './useServices';

type ServiceChainIdAddressRecord = {
  [chainId: number]: {
    agentSafe?: Address;
    agentEoas?: Address[];
  };
};

/**
 * Hook for interacting with a single service.
 */
export const useService = ({
  serviceConfigId,
}: {
  serviceConfigId: string;
}) => {
  const { services, isLoaded } = useServices();

  const service = useMemo(() => {
    return services?.find(
      (service) => service.service_config_id === serviceConfigId,
    );
  }, [serviceConfigId, services]);

  const addresses: ServiceChainIdAddressRecord = useMemo(() => {
    if (!service) return {};
    const chainData = service.chain_configs;

    // group multisigs by chainId
    const addressesByChainId: ServiceChainIdAddressRecord = Object.keys(
      chainData,
    ).reduce((acc, chainIdKey) => {
      const chainId = +chainIdKey;

      const chain = chainData[chainId];
      if (!chain) return acc;

      const { multisig, instances } = chain.chain_data;

      return {
        ...acc,
        [chainId]: {
          agentSafe: multisig,
          agentEoas: instances,
        },
      };
    }, {});

    return addressesByChainId;
  }, [service]);

  return {
    service,
    addresses,
    serviceStatus: MiddlewareDeploymentStatus.DEPLOYED, // TODO support other statuses
    isLoaded,
  };
};
