import { useContext, useMemo } from 'react';

import { BalanceContext, WalletBalanceResult } from '@/context/BalanceProvider';

import { useService } from './useService';
import { useMasterWalletContext } from './useWallet';

export const useBalanceContext = () => useContext(BalanceContext);

/**
 * Balances relevant to a specific service (agent)
 * @param serviceConfigId 
 * @returns 
 */
export const useServiceBalances = (serviceConfigId: string) => {
  const { flatAddresses, masterSafes } = useService({ serviceConfigId });
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

  const isLowBalance = useMemo(
    () => serviceLowBalances?.length > 0,
    [serviceLowBalances],
  );

  const serviceSafeBalances = useMemo<WalletBalanceResult[]>(
    () =>
      walletBalances?.filter((balance) =>
        masterSafes.find(({address}) => balance.walletAddress === address),
      ),
    [flatAddresses, walletBalances],
  );

  return {
    serviceWalletBalances,
    serviceStakedBalances,
    serviceSafeBalances,
    serviceLowBalances,
    isLowBalance,
  };
};

/**
 * Balances relevant to the master wallets, eoa, and safes
 */
// TODO: complete this hook
export const useMasterBalances = () => {
  const { masterSafes, masterEoa } = useMasterWalletContext();
  const { walletBalances, lowBalances, stakedBalances } = useBalanceContext();

  const masterWalletBalances = useMemo(
    () =>
      walletBalances?.filter((balance) =>
        flatAddresses.includes(balance.walletAddress),
      ),
    [flatAddresses, walletBalances],
  );

  const masterStakedBalances = useMemo(
    () =>
      stakedBalances?.filter((balance) =>
        flatAddresses.includes(balance.walletAddress),
      ),
    [flatAddresses, stakedBalances],
  );

  const masterLowBalances = useMemo(
    () => lowBalances?.filter((balance) => balance.walletAddress),
    [lowBalances],
  );

  const isLowBalance = useMemo(
    () => masterLowBalances?.length > 0,
    [masterLowBalances],
  );

  const masterSafeBalances = useMemo<WalletBalanceResult[]>(
    () =>
      walletBalances?.filter((balance) =>
        masterSafes.find(({address}) => balance.walletAddress === address),
      ),
    [flatAddresses, walletBalances],
  );

  return {
    masterWalletBalances,
    masterStakedBalances,
    masterSafeBalances,
    masterLowBalances,
    isLowBalance,
  };
};
