import { round } from 'lodash';
import { useMemo } from 'react';

import { CHAIN_CONFIG } from '@/config/chains';
import { WalletOwnerType, WalletType } from '@/enums/Wallet';
import { useMasterBalances } from '@/hooks/useBalanceContext';
import { useNeedsFunds } from '@/hooks/useNeedsFunds';
import { useServices } from '@/hooks/useServices';
import { useStakingProgram } from '@/hooks/useStakingProgram';
import { useStore } from '@/hooks/useStore';

import { EmptyFunds } from './EmptyFunds';
import { LowOperatingBalanceAlert } from './LowOperatingBalanceAlert';
import { LowSafeSignerBalanceAlert } from './LowSafeSignerBalanceAlert';
import { MainNeedsFunds } from './MainNeedsFunds';

export const LowFunds = () => {
  const { storeState } = useStore();

  const { selectedAgentConfig, selectedAgentType } = useServices();
  const { selectedStakingProgramId } = useStakingProgram();
  const { isLoaded: isBalanceLoaded, masterEoaNativeGasBalance } =
    useMasterBalances();

  const { nativeBalancesByChain, olasBalancesByChain, isInitialFunded } =
    useNeedsFunds(selectedStakingProgramId);

  const chainId = selectedAgentConfig.evmHomeChainId;

  // Check if the safe signer balance is low
  const isSafeSignerBalanceLow = useMemo(() => {
    if (!isBalanceLoaded) return false;
    if (!masterEoaNativeGasBalance) return false;
    if (!storeState?.[`isInitialFunded_${selectedAgentType}`]) return false;

    return (
      masterEoaNativeGasBalance <
      selectedAgentConfig.operatingThresholds[WalletOwnerType.Master][
        WalletType.EOA
      ][CHAIN_CONFIG[selectedAgentConfig.evmHomeChainId].nativeToken.symbol]
    );
  }, [
    isBalanceLoaded,
    masterEoaNativeGasBalance,
    selectedAgentConfig.evmHomeChainId,
    selectedAgentConfig.operatingThresholds,
    selectedAgentType,
    storeState,
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
