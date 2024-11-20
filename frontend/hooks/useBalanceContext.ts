import { useContext, useMemo } from 'react';

import { BalanceContext } from '@/context/BalanceProvider';

import { useService } from './useService';

export const useBalanceContext = () => useContext(BalanceContext);

export const useServiceBalances = (serviceConfigId: string) => {
  const { flatAddresses } = useService({ serviceConfigId });
  const { walletBalances, lowBalances, stakedBalances } = useBalanceContext();

  const serviceWalletBalances = useMemo(
    () =>
      walletBalances?.filter((balance) =>
        flatAddresses.includes(balance.walletAddress),
      ),
    [flatAddresses, walletBalances],
  );

  const serviceStakedBalances = useMemo(
    () =>
      stakedBalances?.filter((balance) =>
        flatAddresses.includes(balance.walletAddress),
      ),
    [flatAddresses, stakedBalances],
  );

  const serviceLowBalances = useMemo(
    () => lowBalances?.filter((balance) => balance.walletAddress),
    [lowBalances],
  );

  return { serviceWalletBalances, serviceLowBalances };
};
