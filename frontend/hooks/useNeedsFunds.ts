import { formatEther, formatUnits } from 'ethers/lib/utils';
import { useMemo } from 'react';

import { ServiceTemplate } from '@/client';
import { CHAIN_CONFIG } from '@/config/chains';
import { STAKING_PROGRAMS } from '@/config/stakingPrograms';
import { getServiceTemplate } from '@/constants/serviceTemplates';

import { useBalanceContext } from './useBalanceContext';
import { useService } from './useService';
import { useStore } from './useStore';
import { TokenSymbol } from '@/enums/Token';
import { getNativeTokenSymbol, NATIVE_TOKEN_CONFIG } from '@/config/tokens';
import { useMasterWalletContext } from './useWallet';

export const useNeedsFunds = (serviceConfigId: string) => {
  const { storeState } = useStore();
  const { service } = useService({ serviceConfigId });
  const { masterSafes } = useMasterWalletContext();
  const { isLoaded: isBalanceLoaded, walletBalances } =
    useBalanceContext();
    

  const isInitialFunded = storeState?.isInitialFunded;

  const serviceTemplate = useMemo<ServiceTemplate | undefined>(
    () => (service ? getServiceTemplate(service.hash) : undefined),
    [service],
  );

  const serviceFundRequirements = useMemo< {
    [chainId: number]: {
      [tokenSymbol: string]: number;    
    }
  }>(() => {
    if (!serviceTemplate) return {};

    const results: {
      [chainId: number]: {
        [tokenSymbol: string]: number;    
      }
    } = {};

    Object.entries(serviceTemplate.configurations).forEach(
      ([chainId, config]) => {
        const serviceTemplateDefault = serviceTemplate.configurations[+chainId].staking_program_id
        const serviceCurrent = service?.chain_configs[+chainId]?.chain_data?.user_params?.staking_program_id

        if (!serviceCurrent && !serviceTemplateDefault) return;

        if (!service?.chain_configs[+chainId]) return;
        const gasEstimate = config.monthly_gas_estimate;
        const monthlyGasEstimate = Number(formatUnits(`${gasEstimate}`, 18));
        const minimumStakedAmountRequired =
          STAKING_PROGRAMS[+chainId][
            service?.chain_configs[+chainId]?.chain_data?.user_params
              ?.staking_program_id ??
              serviceTemplate.configurations[+chainId].staking_program_id
          ].stakingRequirements.OLAS;

        const nativeTokenSymbol = getNativeTokenSymbol(+chainId);

        results[+chainId] = {
          [TokenSymbol.OLAS]: +formatEther(minimumStakedAmountRequired),
          [nativeTokenSymbol]: +formatEther(monthlyGasEstimate),
          // TODO: extend with any further erc20s..
        };
      },
    );

    return results;
  }, [serviceTemplate]);

  const hasEnoughEthForInitialFunding = useMemo(
    () => {
      if (!serviceFundRequirements) return ;
      if (!walletBalances) return ;

      const nativeBalancesByChain = walletBalances.reduce<{[chainId: number]: number}>((acc, {symbol, balance, chainId}) => {
        if (getNativeTokenSymbol(chainId) !== symbol) return acc;
  
        if (!acc[chainId]) acc[chainId] = 0;
        acc[chainId] += balance;      
  
        return acc;
      }, {});

      const chainIds = Object.keys(serviceFundRequirements).map(Number);

      return chainIds.every(chainId => {
        const nativeTokenSymbol = getNativeTokenSymbol(chainId);
        const nativeTokenBalance = nativeBalancesByChain[chainId] || 0;
        const nativeTokenRequired = serviceFundRequirements[chainId]?.[nativeTokenSymbol] || 0;

        return nativeTokenBalance >= nativeTokenRequired;
      });

    },
    [],
  );

  // TODO: refactor this to use the new balance context
  const hasEnoughOlasForInitialFunding = useMemo(() => {
    const olasInSafe = safeBalance?.OLAS || 0;
    const olasStakedBySafe = totalStakedOlasBalance || 0;
    const olasRequiredToFundService = serviceFundRequirements.olas || 0;
    const olasInSafeAndStaked = olasInSafe + olasStakedBySafe;
    return olasInSafeAndStaked >= olasRequiredToFundService;
  }, [
    safeBalance?.OLAS,
    totalStakedOlasBalance,
    serviceFundRequirements?.olas,
  ]);

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
