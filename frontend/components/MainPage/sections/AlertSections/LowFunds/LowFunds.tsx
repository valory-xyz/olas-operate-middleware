import { useMemo } from 'react';

import { LOW_AGENT_SAFE_BALANCE } from '@/constants/thresholds';
import { useMasterBalances } from '@/hooks/useBalanceContext';
import { useNeedsFunds } from '@/hooks/useNeedsFunds';
import { useStakingProgram } from '@/hooks/useStakingProgram';
import { useStore } from '@/hooks/useStore';

import { EmptyFunds } from './EmptyFunds';
import { LowOperatingBalanceAlert } from './LowOperatingBalanceAlert';
import { LowSafeSignerBalanceAlert } from './LowSafeSignerBalanceAlert';
import { MainNeedsFunds } from './MainNeedsFunds';

export const LowFunds = () => {
  const { storeState } = useStore();

  const { selectedStakingProgramId } = useStakingProgram();
  const { isLoaded: isBalanceLoaded, masterEoaNativeGasBalance } =
    useMasterBalances();

  const { nativeBalancesByChain, olasBalancesByChain, isInitialFunded } =
    useNeedsFunds(selectedStakingProgramId);

  const isSafeSignerBalanceLow = useMemo(() => {
    if (!isBalanceLoaded) return false;
    if (!masterEoaNativeGasBalance) return false;
    if (!storeState?.isInitialFunded) return false;

    return masterEoaNativeGasBalance < LOW_AGENT_SAFE_BALANCE;
  }, [isBalanceLoaded, masterEoaNativeGasBalance, storeState]);

  const isEmptyFundsVisible = useMemo(() => {
    if (!isBalanceLoaded) return false;
    if (!olasBalancesByChain) return false;
    if (!nativeBalancesByChain) return false;

    // If the agent is not funded, <MainNeedsFunds /> will be displayed
    if (!isInitialFunded) return false;

    if (
      nativeBalancesByChain[100] === 0 &&
      olasBalancesByChain[100] === 0 &&
      isSafeSignerBalanceLow
    ) {
      return true;
    }

    return false;
  }, [
    isBalanceLoaded,
    isInitialFunded,
    nativeBalancesByChain,
    olasBalancesByChain,
    isSafeSignerBalanceLow,
  ]);

  return (
    <>
      {isEmptyFundsVisible && <EmptyFunds />}
      <MainNeedsFunds />
      <LowOperatingBalanceAlert />
      {!isEmptyFundsVisible && isSafeSignerBalanceLow && (
        <LowSafeSignerBalanceAlert />
      )}
    </>
  );
};
