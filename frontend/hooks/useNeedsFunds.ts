import { formatEther, formatUnits } from 'ethers/lib/utils';
import { isNil } from 'lodash';
import { useMemo } from 'react';

import { STAKING_PROGRAMS } from '@/config/stakingPrograms';
import { getNativeTokenSymbol } from '@/config/tokens';
import { SERVICE_TEMPLATES } from '@/constants/serviceTemplates';
import { TokenSymbol } from '@/enums/Token';
import { asEvmChainId } from '@/utils/middlewareHelpers';

import { useBalanceContext, useMasterBalances } from './useBalanceContext';
import { useServices } from './useServices';
import { useStore } from './useStore';

export const useNeedsFunds = (stakingProgramId?: string) => {
  const { storeState } = useStore();

  const { selectedAgentType } = useServices();
  const serviceTemplate = SERVICE_TEMPLATES.find(
    (template) => template.agentType === selectedAgentType,
  );

  const { isLoaded: isBalanceLoaded, walletBalances } = useBalanceContext();

  const { masterSafeBalances } = useMasterBalances();

  const isInitialFunded = storeState?.isInitialFunded;

  const serviceFundRequirements = useMemo<{
    [chainId: number]: {
      [tokenSymbol: string]: number;
    };
  }>(() => {
    if (isNil(serviceTemplate)) return {};

    const results: {
      [chainId: number]: {
        [tokenSymbol: string]: number;
      };
    } = {};

    Object.entries(serviceTemplate.configurations).forEach(
      ([middlewareChain, config]) => {
        const evmChainId = asEvmChainId(middlewareChain);

        const templateStakingProgramId =
          serviceTemplate.configurations[middlewareChain].staking_program_id;

        // if stakingProgramId not provided, use the one from the template
        const resolvedStakingProgramId =
          stakingProgramId ?? templateStakingProgramId;

        if (!resolvedStakingProgramId) return;

        const gasEstimate = config.monthly_gas_estimate;
        const monthlyGasEstimate = Number(formatUnits(`${gasEstimate}`, 18));
        const minimumStakedAmountRequired =
          STAKING_PROGRAMS[evmChainId]?.[resolvedStakingProgramId]
            ?.stakingRequirements?.[TokenSymbol.OLAS] || 0;

        const nativeTokenSymbol = getNativeTokenSymbol(evmChainId);

        results[evmChainId] = {
          [TokenSymbol.OLAS]: +formatEther(minimumStakedAmountRequired),
          [nativeTokenSymbol]: +formatEther(monthlyGasEstimate),
          // TODO: extend with any further erc20s..
        };
      },
    );

    return results;
  }, [serviceTemplate, stakingProgramId]);

  const hasEnoughEthForInitialFunding = useMemo(() => {
    if (isNil(serviceFundRequirements)) return;
    if (isNil(walletBalances)) return;

    const nativeBalancesByChain = walletBalances.reduce<{
      [chainId: number]: number;
    }>((acc, { symbol, balance, evmChainId }) => {
      if (getNativeTokenSymbol(evmChainId) !== symbol) return acc;

      if (!acc[evmChainId]) acc[evmChainId] = 0;
      acc[evmChainId] += balance;

      return acc;
    }, {});

    const chainIds = Object.keys(serviceFundRequirements).map(Number);

    return chainIds.every((chainId) => {
      const nativeTokenSymbol = getNativeTokenSymbol(chainId);
      const nativeTokenBalance = nativeBalancesByChain[chainId] || 0;
      const nativeTokenRequired =
        serviceFundRequirements[chainId]?.[nativeTokenSymbol] || 0;

      return nativeTokenBalance >= nativeTokenRequired;
    });
  }, [serviceFundRequirements, walletBalances]);

  const hasEnoughOlasForInitialFunding = useMemo(() => {
    if (!serviceFundRequirements) return;
    if (!masterSafeBalances) return;

    const olasBalancesByChain = masterSafeBalances.reduce<{
      [chainId: number]: number;
    }>((acc, { symbol, balance, evmChainId }) => {
      if (TokenSymbol.OLAS !== symbol) return acc;

      if (!acc[evmChainId]) acc[evmChainId] = 0;
      acc[evmChainId] += balance;

      return acc;
    }, {});

    const chainIds = Object.keys(serviceFundRequirements).map(Number);

    return chainIds.every((chainId) => {
      const olasBalance = olasBalancesByChain[chainId] || 0;
      const olasRequired =
        serviceFundRequirements[chainId]?.[TokenSymbol.OLAS] || 0;

      return olasBalance >= olasRequired;
    });
  }, [masterSafeBalances, serviceFundRequirements]);

  const needsInitialFunding: boolean = useMemo(() => {
    if (isInitialFunded) return false;
    if (!isBalanceLoaded) return false;
    if (hasEnoughEthForInitialFunding && hasEnoughOlasForInitialFunding)
      return false;
    return true;
  }, [
    hasEnoughEthForInitialFunding,
    hasEnoughOlasForInitialFunding,
    isBalanceLoaded,
    isInitialFunded,
  ]);

  return {
    hasEnoughEthForInitialFunding,
    hasEnoughOlasForInitialFunding,
    serviceFundRequirements,
    isInitialFunded,
    needsInitialFunding,
  };
};
