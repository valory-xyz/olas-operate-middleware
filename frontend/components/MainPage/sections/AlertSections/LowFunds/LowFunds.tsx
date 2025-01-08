import { isEmpty, round } from 'lodash';
import { useMemo } from 'react';

import { getNativeTokenSymbol } from '@/config/tokens';
import { TokenSymbol } from '@/enums/Token';
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
  const { isMasterEoaLowOnGas } = useMasterBalances();

  const { balancesByChain, isInitialFunded } = useNeedsFunds(
    selectedStakingProgramId,
  );

  const chainId = selectedAgentConfig.evmHomeChainId;

  // Show the empty funds alert if the agent is not funded
  const isEmptyFundsVisible = useMemo(() => {
    if (isEmpty(balancesByChain)) return false;

    // If the agent is not funded, <MainNeedsFunds /> will be displayed
    if (!isInitialFunded) return false;

    const balances = balancesByChain[chainId];
    if (
      round(balances[getNativeTokenSymbol(chainId)], 2) === 0 &&
      round(balances[TokenSymbol.OLAS], 2) === 0 &&
      isMasterEoaLowOnGas
    ) {
      return true;
    }

    return false;
  }, [isInitialFunded, chainId, isMasterEoaLowOnGas, balancesByChain]);

  return (
    <>
      {isEmptyFundsVisible && <EmptyFunds />}
      <MainNeedsFunds />
      <LowOperatingBalanceAlert />
      {!isEmptyFundsVisible && isMasterEoaLowOnGas && (
        <LowSafeSignerBalanceAlert />
      )}
    </>
  );
};
