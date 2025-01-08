import { createContext, PropsWithChildren } from 'react';

export const BalancesAndFundRequirementsProviderContext = createContext<{
  hasEnoughEthForInitialFunding: boolean;
}>({
  hasEnoughEthForInitialFunding: false,
});

export const BalancesAndFundRequirementsProvider = ({
  children,
}: PropsWithChildren) => {
  return (
    <BalancesAndFundRequirementsProviderContext.Provider
      value={{ hasEnoughEthForInitialFunding: false }}
    >
      {children}
    </BalancesAndFundRequirementsProviderContext.Provider>
  );
};
