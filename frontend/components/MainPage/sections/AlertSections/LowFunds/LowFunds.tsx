import { round } from 'lodash';
import { useMemo } from 'react';

import { CHAIN_CONFIG } from '@/config/chains';
import { WalletOwnerType, WalletType } from '@/enums/Wallet';
import { useMasterBalances } from '@/hooks/useBalanceContext';
import { useNeedsFunds } from '@/hooks/useNeedsFunds';
import { useServices } from '@/hooks/useServices';
import { useStakingProgram } from '@/hooks/useStakingProgram';

import { EmptyFunds } from './EmptyFunds';
import { LowOperatingBalanceAlert } from './LowOperatingBalanceAlert';
import { LowSafeSignerBalanceAlert } from './LowSafeSignerBalanceAlert';
import { MainNeedsFunds } from './MainNeedsFunds';

export const LowFunds = () => {
  const { selectedAgentConfig } = useServices();
  const { selectedStakingProgramId } = useStakingProgram();
  const {
    isLoaded: isBalanceLoaded,
    masterEoaNativeGasBalance,
    masterSafeNativeGasBalance,
  } = useMasterBalances();

  const { nativeBalancesByChain, olasBalancesByChain, isInitialFunded } =
    useNeedsFunds(selectedStakingProgramId);

  const chainId = selectedAgentConfig.evmHomeChainId;

  // Check if the safe signer balance is low
  const isSafeSignerBalanceLow = useMemo(() => {
    if (!isBalanceLoaded) return false;
    if (!masterEoaNativeGasBalance) return false;
    if (!masterSafeNativeGasBalance) return false;
    if (!isInitialFunded) return false;

    const masterThresholds =
      selectedAgentConfig.operatingThresholds[WalletOwnerType.Master];
    const tokenSymbol =
      CHAIN_CONFIG[selectedAgentConfig.evmHomeChainId].nativeToken.symbol;

    return (
      masterEoaNativeGasBalance < masterThresholds[WalletType.EOA][tokenSymbol]
    );
  }, [
    isBalanceLoaded,
    isInitialFunded,
    masterEoaNativeGasBalance,
    masterSafeNativeGasBalance,
    selectedAgentConfig.evmHomeChainId,
    selectedAgentConfig.operatingThresholds,
  ]);

  // Show the empty funds alert if the agent is not funded
  const isEmptyFundsVisible = useMemo(() => {
    if (!isBalanceLoaded) return false;
    if (!olasBalancesByChain) return false;
    if (!nativeBalancesByChain) return false;

    // If the agent is not funded, <MainNeedsFunds /> will be displayed
    if (!isInitialFunded) return false;

    if (
      round(nativeBalancesByChain[chainId], 2) === 0 &&
      round(olasBalancesByChain[chainId], 2) === 0 &&
      isSafeSignerBalanceLow
    ) {
      return true;
    }

    return false;
  }, [
    isBalanceLoaded,
    isInitialFunded,
    chainId,
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
