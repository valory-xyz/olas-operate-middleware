import { useQuery, useQueryClient } from '@tanstack/react-query';
import { isNil } from 'lodash';
import {
  createContext,
  PropsWithChildren,
  useCallback,
  useEffect,
  useState,
} from 'react';

import { DEFAULT_STAKING_PROGRAM_IDS } from '@/config/stakingPrograms';
import { FIVE_SECONDS_INTERVAL } from '@/constants/intervals';
import { REACT_QUERY_KEYS } from '@/constants/react-query-keys';
import { StakingProgramId } from '@/enums/StakingProgram';
import { useService } from '@/hooks/useService';
import { useServices } from '@/hooks/useServices';
import { Maybe, Nullable, Optional } from '@/types/Util';

export const StakingProgramContext = createContext<{
  isActiveStakingProgramLoaded: boolean;
  activeStakingProgramId?: Maybe<StakingProgramId>;
  defaultStakingProgramId?: Maybe<StakingProgramId>;
  selectedStakingProgramId: Nullable<StakingProgramId>;
  setDefaultStakingProgramId: (stakingProgramId: StakingProgramId) => void;
}>({
  isActiveStakingProgramLoaded: false,
  selectedStakingProgramId: null,
  setDefaultStakingProgramId: () => {},
});

/**
 * hook to get the active staking program id
 */
const useGetActiveStakingProgramId = (serviceNftTokenId: Optional<number>) => {
  const queryClient = useQueryClient();
  const { selectedAgentConfig, isFetched: isServicesLoaded } = useServices();

  const { serviceApi, evmHomeChainId } = selectedAgentConfig;

  const response = useQuery({
    queryKey: REACT_QUERY_KEYS.STAKING_PROGRAM_KEY(evmHomeChainId),
    queryFn: async () => {
      if (isNil(serviceNftTokenId)) return null;

      const currentStakingProgramId =
        await serviceApi.getCurrentStakingProgramByServiceId(
          serviceNftTokenId,
          evmHomeChainId,
        );

      return (
        currentStakingProgramId ||
        DEFAULT_STAKING_PROGRAM_IDS[selectedAgentConfig.evmHomeChainId]
      );
    },
    enabled:
      !isNil(evmHomeChainId) && isServicesLoaded && !isNil(serviceNftTokenId),
    refetchInterval: isServicesLoaded ? FIVE_SECONDS_INTERVAL : 0,
  });

  const setActiveStakingProgramId = useCallback(
    (stakingProgramId: Nullable<StakingProgramId>) => {
      if (!serviceNftTokenId)
        throw new Error(
          'serviceNftTokenId is required to set the active staking program id',
        );
      if (!stakingProgramId)
        throw new Error(
          'stakingProgramId is required to set the active staking program id',
        );

      // update the active staking program id in the cache
      queryClient.setQueryData(
        REACT_QUERY_KEYS.STAKING_PROGRAM_KEY(evmHomeChainId, serviceNftTokenId),
        stakingProgramId,
      );
    },
    [queryClient, evmHomeChainId, serviceNftTokenId],
  );

  return { ...response, setActiveStakingProgramId };
};

/**
 * context provider responsible for determining the current active staking program based on the service.
 * It does so by checking if the current service is staked, and if so, which staking program it is staked in.
 * It also provides a method to update the active staking program id in state.
 *
 * When the service is not yet deployed, a default staking program state is used to allow switching
 * between staking programs before deployment is complete, ensuring the relevant staking program is displayed,
 * even if deployment is still in progress
 */
export const StakingProgramProvider = ({ children }: PropsWithChildren) => {
  const { selectedService, selectedAgentConfig } = useServices();

  const { service } = useService(selectedService?.service_config_id);

  const [defaultStakingProgramId, setDefaultStakingProgramId] = useState(
    DEFAULT_STAKING_PROGRAM_IDS[selectedAgentConfig.evmHomeChainId],
  );

  useEffect(() => {
    setDefaultStakingProgramId(
      DEFAULT_STAKING_PROGRAM_IDS[selectedAgentConfig.evmHomeChainId],
    );
  }, [selectedAgentConfig]);

  const serviceNftTokenId =
    service?.chain_configs[service?.home_chain]?.chain_data?.token;

  const {
    isFetched: isActiveStakingProgramLoaded,
    data: activeStakingProgramId,
  } = useGetActiveStakingProgramId(serviceNftTokenId);

  const selectedStakingProgramId = isActiveStakingProgramLoaded
    ? activeStakingProgramId || defaultStakingProgramId
    : null;

  return (
    <StakingProgramContext.Provider
      value={{
        isActiveStakingProgramLoaded,
        activeStakingProgramId,
        defaultStakingProgramId,
        selectedStakingProgramId,
        setDefaultStakingProgramId,
      }}
    >
      {children}
    </StakingProgramContext.Provider>
  );
};
