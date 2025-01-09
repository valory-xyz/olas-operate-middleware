import { useQuery } from '@tanstack/react-query';
import { createContext, PropsWithChildren, useMemo } from 'react';

import { AddressBalanceRecord, BalancesAndFundingRequirements } from '@/client';
import { FIVE_SECONDS_INTERVAL } from '@/constants/intervals';
import { REACT_QUERY_KEYS } from '@/constants/react-query-keys';
import { useServices } from '@/hooks/useServices';
import { BalanceService } from '@/service/balances';
import { Optional } from '@/types/Util';
import { asMiddlewareChain } from '@/utils/middlewareHelpers';

export const BalancesAndRefillRequirementsProviderContext = createContext<{
  isBalancesAndFundingRequirementsLoading: boolean;
  balances: Optional<AddressBalanceRecord>;
  refillRequirements: Optional<AddressBalanceRecord>;
  canStartAgent: boolean;
}>({
  isBalancesAndFundingRequirementsLoading: false,
  balances: undefined,
  refillRequirements: undefined,
  canStartAgent: false,
});

export const BalancesAndRefillRequirementsProvider = ({
  children,
}: PropsWithChildren) => {
  const { selectedService, selectedAgentConfig } = useServices();
  const configId = selectedService?.service_config_id;
  const chainId = selectedAgentConfig.evmHomeChainId;

  const {
    data: balancesAndRefillRequirements,
    isLoading: isBalancesAndFundingRequirementsLoading,
  } = useQuery<BalancesAndFundingRequirements>({
    queryKey: REACT_QUERY_KEYS.BALANCES_AND_REFILL_REQUIREMENTS_KEY(
      configId as string,
    ),
    queryFn: () =>
      BalanceService.getBalancesAndFundingRequirements(configId as string),
    enabled: !!configId,
    refetchInterval: FIVE_SECONDS_INTERVAL * 20, // TODO: 60 seconds if agent is already running else 5 seconds
  });

  const balances = useMemo(() => {
    if (isBalancesAndFundingRequirementsLoading) return;
    if (!balancesAndRefillRequirements) return;

    return balancesAndRefillRequirements.balances[asMiddlewareChain(chainId)];
  }, [
    balancesAndRefillRequirements,
    chainId,
    isBalancesAndFundingRequirementsLoading,
  ]);

  const refillRequirements = useMemo(() => {
    if (isBalancesAndFundingRequirementsLoading) return;
    if (!balancesAndRefillRequirements) return;

    // TODO: update here
    return balancesAndRefillRequirements.user_fund_requirements[
      asMiddlewareChain(chainId)
    ];
  }, [
    balancesAndRefillRequirements,
    chainId,
    isBalancesAndFundingRequirementsLoading,
  ]);

  return (
    <BalancesAndRefillRequirementsProviderContext.Provider
      value={{
        isBalancesAndFundingRequirementsLoading,
        refillRequirements,
        balances,
        canStartAgent:
          balancesAndRefillRequirements?.allow_start_agent || false,
      }}
    >
      {children}
    </BalancesAndRefillRequirementsProviderContext.Provider>
  );
};
