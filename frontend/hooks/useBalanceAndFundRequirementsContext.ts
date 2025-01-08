import { useContext } from 'react';

import { BalancesAndFundRequirementsProviderContext } from '@/context/BalancesAndFundRequirementsProvider';

export const useBalanceAndFundRequirementsContext = () =>
  useContext(BalancesAndFundRequirementsProviderContext);
