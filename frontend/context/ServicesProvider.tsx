import { QueryObserverBaseResult, useQuery } from '@tanstack/react-query';
import { isEmpty, noop } from 'lodash';
import {
  createContext,
  PropsWithChildren,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';

import { MiddlewareChain, MiddlewareServiceResponse } from '@/client';
import { AGENT_CONFIG } from '@/config/agents';
import { FIVE_SECONDS_INTERVAL } from '@/constants/intervals';
import { REACT_QUERY_KEYS } from '@/constants/react-query-keys';
import { AgentType } from '@/enums/Agent';
import {
  AgentEoa,
  AgentSafe,
  AgentWallets,
  WalletOwnerType,
  WalletType,
} from '@/enums/Wallet';
import { UsePause, usePause } from '@/hooks/usePause';
import { ServicesService } from '@/service/Services';
import { AgentConfig } from '@/types/Agent';
import { Service } from '@/types/Service';
import { Maybe } from '@/types/Util';
import { asEvmChainId } from '@/utils/middlewareHelpers';

import { OnlineStatusContext } from './OnlineStatusProvider';

type ServicesContextType = {
  services?: MiddlewareServiceResponse[];
  serviceWallets?: AgentWallets;
  // servicesByMiddlewareChain?: Record<
  //   string | MiddlewareChain,
  //   MiddlewareServiceResponse[]
  // >;
  // servicesByEvmChainId?: Record<
  //   number | EvmChainId,
  //   MiddlewareServiceResponse[]
  // >;
  selectService: (serviceUuid: string) => void;
  selectedService?: Service;
  selectedAgentConfig: AgentConfig;
  selectedAgentType: AgentType;
  updateAgentType: (agentType: AgentType) => void;
} & Partial<QueryObserverBaseResult<MiddlewareServiceResponse[]>> &
  UsePause;

export const ServicesContext = createContext<ServicesContextType>({
  paused: false,
  setPaused: noop,
  togglePaused: noop,
  selectService: noop,
  selectedAgentConfig: AGENT_CONFIG[AgentType.PredictTrader],
  selectedAgentType: AgentType.PredictTrader,
  updateAgentType: noop,
});

/**
 * Polls for available services via the middleware API globally
 */
export const ServicesProvider = ({ children }: PropsWithChildren) => {
  const { isOnline } = useContext(OnlineStatusContext);
  const { paused, setPaused, togglePaused } = usePause();

  // selected agent type
  const [selectedAgentType, setAgentType] = useState<AgentType>(
    AgentType.PredictTrader,
  );

  // user selected service identifier
  const [selectedServiceConfigId, setSelectedServiceConfigId] =
    useState<string>();

  const {
    data: services,
    isError,
    isFetched,
    isLoading,
    isFetching,
    refetch,
  } = useQuery<MiddlewareServiceResponse[]>({
    queryKey: REACT_QUERY_KEYS.SERVICES_KEY,
    queryFn: ServicesService.getServices,
    enabled: isOnline && !paused,
    refetchInterval: FIVE_SECONDS_INTERVAL,
  });

  const selectedService = useMemo<Service | undefined>(() => {
    if (!services) return;
    return services.find(
      (service) => service.service_config_id === selectedServiceConfigId,
    );
  }, [selectedServiceConfigId, services]);

  const selectService = useCallback((serviceUuid: string) => {
    setSelectedServiceConfigId(serviceUuid);
  }, []);

  const updateAgentType = useCallback((agentType: AgentType) => {
    setAgentType(agentType);
  }, []);

  const selectedAgentConfig = useMemo(() => {
    const config: Maybe<AgentConfig> = AGENT_CONFIG[selectedAgentType];

    if (!config) {
      throw new Error(`Agent config not found for ${selectedAgentType}`);
    }
    return config;
  }, [selectedAgentType]);

  // const servicesByHomeMiddlewareChain = useMemo(() => {
  //   if (!isFetched) return;
  //   if (!services) return;
  //   return services.reduce<
  //     Record<string | MiddlewareChain, MiddlewareServiceResponse[]>
  //   >((acc, service) => {
  //     if (!acc[service.home_chain]) {
  //       acc[service.home_chain] = [service.chain_configs[]];
  //       return acc;
  //     }

  //     acc[service.home_chain].push(service);
  //     return acc;
  //   }, {});
  // }, [isFetched, services]);

  // const servicesByHomeEvmChainId = useMemo(() => {
  //   if (!isFetched) return;
  //   if (!services) return;
  //   return Object.keys(EvmChainId).reduce<
  //     Record<number, MiddlewareServiceResponse[]>
  //   >((acc, evmChainIdKey) => {
  //     const evmChainId = EvmChainId[evmChainIdKey as keyof typeof EvmChainId];

  //     acc[evmChainId] = services.filter(
  //       (service: MiddlewareServiceResponse) =>
  //         service.chain_configs[asMiddlewareChain(evmChainId)],
  //     );
  //     return acc;
  //   }, {});
  // }, [isFetched, services]);

  const serviceAddresses = useMemo(() => {
    if (!isFetched) return;
    if (isEmpty(services)) return [];

    return services?.reduce<AgentWallets>(
      (acc, service: MiddlewareServiceResponse) => {
        return [
          ...acc,
          ...Object.keys(service.chain_configs).reduce(
            (acc: AgentWallets, middlewareChain: string) => {
              const chainConfig =
                service.chain_configs[middlewareChain as MiddlewareChain];

              if (!chainConfig) return acc;

              const instances = chainConfig.chain_data.instances;
              const multisig = chainConfig.chain_data.multisig;

              if (instances) {
                acc.push(
                  ...instances.map(
                    (instance: string) =>
                      ({
                        address: instance,
                        type: WalletType.EOA,
                        owner: WalletOwnerType.Agent,
                      }) as AgentEoa,
                  ),
                );
              }

              if (multisig) {
                acc.push({
                  address: multisig,
                  type: WalletType.Safe,
                  owner: WalletOwnerType.Agent,
                  evmChainId: asEvmChainId(middlewareChain),
                } as AgentSafe);
              }

              return acc;
            },
            [],
          ),
        ];
      },
      [],
    );
  }, [isFetched, services]);

  /**
   * Select the first service by default
   */
  useEffect(() => {
    if (!services) return;
    if (selectedServiceConfigId) return;
    // only select a service by default if services are fetched, but there has been no selection yet
    if (isFetched && services.length > 0 && !selectedServiceConfigId)
      setSelectedServiceConfigId(services[0].service_config_id);
  }, [isFetched, selectedServiceConfigId, services]);

  // const updateServiceStatus = useCallback(async () => {
  //   if (!services?.[0]) return;
  //   const serviceStatus = await ServicesService.getDeployment(services[0].service_config_id);
  //   setServiceStatuses(serviceStatus.status);
  // }, [services]);

  return (
    <ServicesContext.Provider
      value={{
        services,
        serviceWallets: serviceAddresses,
        // servicesByMiddlewareChain: servicesByHomeMiddlewareChain,
        // servicesByEvmChainId: servicesByHomeEvmChainId,
        isError,
        isFetched,
        isLoading,
        isFetching,
        refetch,
        paused,
        setPaused,
        togglePaused,
        selectService,
        selectedService,
        selectedAgentConfig,
        selectedAgentType,
        updateAgentType,
      }}
    >
      {children}
    </ServicesContext.Provider>
  );
};
