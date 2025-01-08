import { useQuery } from '@tanstack/react-query';
import { createContext, PropsWithChildren, useMemo } from 'react';

import { AddressBalanceRecord, BalancesAndFundingRequirements } from '@/client';
import { FIVE_SECONDS_INTERVAL } from '@/constants/intervals';
import { REACT_QUERY_KEYS } from '@/constants/react-query-keys';
import { useServices } from '@/hooks/useServices';
import { BalanceService } from '@/service/balances';
import { Optional } from '@/types/Util';
import { asMiddlewareChain } from '@/utils/middlewareHelpers';

export const BalancesAndFundRequirementsProviderContext = createContext<{
  isBalancesAndFundingRequirementsLoading: boolean;
  balances: Optional<AddressBalanceRecord>;
  userFundRequirements: Optional<AddressBalanceRecord>;
  canStartAgent: boolean;
}>({
  isBalancesAndFundingRequirementsLoading: false,
  balances: undefined,
  userFundRequirements: undefined,
  canStartAgent: false,
});

export const BalancesAndFundRequirementsProvider = ({
  children,
}: PropsWithChildren) => {
  const { selectedService, selectedAgentConfig } = useServices();
  const configId = selectedService?.service_config_id;
  const chainId = selectedAgentConfig.evmHomeChainId;

  const {
    data: balancesAndFundingRequirements,
    isLoading: isBalancesAndFundingRequirementsLoading,
  } = useQuery<BalancesAndFundingRequirements>({
    queryKey: REACT_QUERY_KEYS.BALANCES_AND_FUNDING_REQUIREMENTS_KEY(
      configId as string,
    ),
    queryFn: () =>
      BalanceService.getBalancesAndFundingRequirements(configId as string),
    enabled: !!selectedService?.service_config_id,
    refetchInterval: FIVE_SECONDS_INTERVAL * 20, // TODO: 60 seconds if agent is already running else 5 seconds
  });

  const balances = useMemo(() => {
    if (isBalancesAndFundingRequirementsLoading) return;
    if (!balancesAndFundingRequirements) return;

    return balancesAndFundingRequirements.balances[asMiddlewareChain(chainId)];
  }, [
    balancesAndFundingRequirements,
    chainId,
    isBalancesAndFundingRequirementsLoading,
  ]);

  const userFundRequirements = useMemo(() => {
    if (isBalancesAndFundingRequirementsLoading) return;
    if (!balancesAndFundingRequirements) return;

    return balancesAndFundingRequirements.user_fund_requirements[
      asMiddlewareChain(chainId)
    ];
  }, [
    balancesAndFundingRequirements,
    chainId,
    isBalancesAndFundingRequirementsLoading,
  ]);

  return (
    <BalancesAndFundRequirementsProviderContext.Provider
      value={{
        isBalancesAndFundingRequirementsLoading,
        userFundRequirements,
        balances,
        canStartAgent:
          balancesAndFundingRequirements?.allow_start_agent || false,
      }}
    >
      {children}
    </BalancesAndFundRequirementsProviderContext.Provider>
  );
};
