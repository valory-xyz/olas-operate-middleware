import { useQuery, useQueryClient } from '@tanstack/react-query';
import { createContext, PropsWithChildren, useCallback } from 'react';

import { INITIAL_DEFAULT_STAKING_PROGRAM_IDS } from '@/config/stakingPrograms';
import { FIVE_SECONDS_INTERVAL } from '@/constants/intervals';
import { REACT_QUERY_KEYS } from '@/constants/react-query-keys';
import { StakingProgramId } from '@/enums/StakingProgram';
import { useService } from '@/hooks/useService';
import { useServices } from '@/hooks/useServices';
import { Maybe, Nullable } from '@/types/Util';

export const StakingProgramContext = createContext<{
  isActiveStakingProgramLoaded: boolean;
  initialDefaultStakingProgramId: Maybe<StakingProgramId>;
  activeStakingProgramId: Maybe<StakingProgramId>;
}>({
  isActiveStakingProgramLoaded: false,
  activeStakingProgramId: null,
  initialDefaultStakingProgramId: null,
});

/**
 * hook to get the active staking program id
 */
const useGetActiveStakingProgramId = (serviceNftTokenId: Maybe<number>) => {
  const queryClient = useQueryClient();
  const { selectedAgentConfig } = useServices();

  const { serviceApi, evmHomeChainId: homeChainId } = selectedAgentConfig;

  const response = useQuery({
    queryKey: REACT_QUERY_KEYS.STAKING_PROGRAM_KEY(
      homeChainId,
      serviceNftTokenId!,
    ),
    queryFn: async () => {
      const response = await serviceApi.getCurrentStakingProgramByServiceId(
        serviceNftTokenId!,
        homeChainId,
      );
      return (
        response ||
        INITIAL_DEFAULT_STAKING_PROGRAM_IDS[selectedAgentConfig.evmHomeChainId]
      );
    },
    enabled: !!homeChainId && !!serviceNftTokenId,
    refetchInterval: serviceNftTokenId ? FIVE_SECONDS_INTERVAL : false,
  });

  const setActiveStakingProgramId = useCallback(
    (stakingProgramId: Nullable<StakingProgramId>) => {
      if (!serviceNftTokenId) return;
      if (!stakingProgramId) return;

      // update the active staking program id in the cache
      queryClient.setQueryData(
        REACT_QUERY_KEYS.STAKING_PROGRAM_KEY(homeChainId, serviceNftTokenId),
        stakingProgramId,
      );
    },
    [queryClient, homeChainId, serviceNftTokenId],
  );

  return { ...response, setActiveStakingProgramId };
};

/**
 * context provider responsible for determining the current active staking programs.
 * It does so by checking if the current service is staked, and if so, which staking program it is staked in.
 * It also provides a method to update the active staking program id in state.
 */
export const StakingProgramProvider = ({ children }: PropsWithChildren) => {
  const {
    selectedService,
    selectedAgentConfig,
    isFetched: isLoaded,
  } = useServices();
  const serviceConfigId =
    isLoaded && selectedService ? selectedService?.service_config_id : '';
  const { service } = useService(serviceConfigId);

  const serviceNftTokenId =
    service?.chain_configs[service?.home_chain]?.chain_data?.token;

  const { isLoading: isStakingProgramsLoading, data: activeStakingProgramId } =
    useGetActiveStakingProgramId(serviceNftTokenId);

  return (
    <StakingProgramContext.Provider
      value={{
        isActiveStakingProgramLoaded:
          !isStakingProgramsLoading && !!activeStakingProgramId,
        activeStakingProgramId,
        initialDefaultStakingProgramId:
          INITIAL_DEFAULT_STAKING_PROGRAM_IDS[selectedAgentConfig.evmHomeChainId],
      }}
    >
      {children}
    </StakingProgramContext.Provider>
  );
};
