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
import { Maybe, Optional } from '@/types/Util';
import { asEvmChainId } from '@/utils/middlewareHelpers';

import { OnlineStatusContext } from './OnlineStatusProvider';

type ServicesContextType = {
  services?: MiddlewareServiceResponse[];
  serviceWallets?: AgentWallets;
  selectService: (serviceConfigId: string) => void;
  selectedService?: Service;
  isSelectedServiceStatusFetched: boolean;
  refetchSelectedServiceStatus: () => void;
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
  isSelectedServiceStatusFetched: false,
  refetchSelectedServiceStatus: noop,
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

  const {
    data: selectedServiceStatus,
    isFetched: isSelectedServiceStatusFetched,
    refetch: refetchSelectedServiceStatus,
  } = useQuery({
    queryKey: REACT_QUERY_KEYS.SERVICE_STATUS_KEY(selectedServiceConfigId),
    queryFn: () =>
      ServicesService.getDeployment(selectedServiceConfigId as string),
    enabled: !!selectedServiceConfigId,
    refetchInterval: FIVE_SECONDS_INTERVAL,
  });

  const selectedService = useMemo<Service | undefined>(() => {
    if (!services) return;

    const selectedService = services.find(
      (service) => service.service_config_id === selectedServiceConfigId,
    );

    return {
      ...selectedService,
      deploymentStatus: selectedServiceStatus?.status,
    } as Service;
  }, [selectedServiceConfigId, selectedServiceStatus?.status, services]);

  const selectedServiceWithStatus = useMemo<Service | undefined>(() => {
    if (!selectedService) return;
    return {
      ...selectedService,
      deploymentStatus: selectedServiceStatus?.status,
    };
  }, [selectedService, selectedServiceStatus?.status]);

  const selectService = useCallback((serviceConfigId: string) => {
    setSelectedServiceConfigId(serviceConfigId);
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

  const serviceWallets: Optional<AgentWallets> = useMemo(() => {
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

  return (
    <ServicesContext.Provider
      value={{
        services,
        serviceWallets,
        isError,
        isFetched,
        isLoading,
        isFetching,
        refetch,
        paused,
        setPaused,
        togglePaused,
        selectService,
        selectedService: selectedServiceWithStatus,
        refetchSelectedServiceStatus,
        isSelectedServiceStatusFetched,
        selectedAgentConfig,
        selectedAgentType,
        updateAgentType,
      }}
    >
      {children}
    </ServicesContext.Provider>
  );
};
