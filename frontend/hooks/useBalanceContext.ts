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
  const { flatAddresses, serviceSafes: masterSafes } = useService({
    serviceConfigId,
  });
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
        masterSafes.find(({ address }) => balance.walletAddress === address),
      ),
    [masterSafes, walletBalances],
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
 * @note master wallets are *shared* wallets across all services
 * @note master safe addresses are deterministic, and should be the same
 */
export const useMasterBalances = () => {
  const { masterSafes, masterEoa } = useMasterWalletContext();
  const { walletBalances, lowBalances, stakedBalances } = useBalanceContext();

  const masterWalletBalances = useMemo(
    () =>
      walletBalances?.filter(
        (balance) =>
          masterSafes?.find((safe) => safe.address === balance.walletAddress) ||
          masterEoa?.address === balance.walletAddress,
      ),
    [masterEoa?.address, masterSafes, walletBalances],
  );

  const masterStakedBalances = useMemo(
    () =>
      stakedBalances?.filter((balance) =>
        masterSafes?.find((safe) => safe.address === balance.walletAddress),
      ),
    [masterSafes, stakedBalances],
  );

  const masterLowBalances = useMemo(
    () => lowBalances?.filter((balance) => balance.walletAddress),
    [lowBalances],
  );

  const isLowBalance = useMemo(
    () => masterLowBalances?.length > 0,
    [masterLowBalances],
  );
  // use flatAddresses for consistency
  const masterSafeBalances = useMemo<WalletBalanceResult[]>(
    () =>
      walletBalances?.filter((balance) =>
        masterSafes?.find(({ address }) => balance.walletAddress === address),
      ),
    [masterSafes, walletBalances],
  );

  return {
    masterWalletBalances,
    masterStakedBalances,
    masterSafeBalances,
    masterLowBalances,
    isLowBalance,
  };
};
