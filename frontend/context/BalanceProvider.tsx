import { message } from 'antd';
import { BigNumberish } from 'ethers';
import { isAddress } from 'ethers/lib/utils';
import { Contract as MulticallContract } from 'ethers-multicall';
import { isNil } from 'lodash';
import { ValueOf } from 'next/dist/shared/lib/constants';
import {
  createContext,
  Dispatch,
  PropsWithChildren,
  SetStateAction,
  useCallback,
  useContext,
  useMemo,
  useState,
} from 'react';
import { useInterval } from 'usehooks-ts';

import { ERC20_BALANCE_OF_STRING_FRAGMENT } from '@/abis/erc20';
import { CHAIN_CONFIG } from '@/config/chains';
import { TOKEN_CONFIG, TokenType } from '@/config/tokens';
import { FIVE_SECONDS_INTERVAL } from '@/constants/intervals';
import { PROVIDERS } from '@/constants/providers';
import {
  LOW_AGENT_SAFE_BALANCE,
  LOW_MASTER_SAFE_BALANCE,
} from '@/constants/thresholds';
import { ChainId } from '@/enums/Chain';
import { ServiceRegistryL2ServiceState } from '@/enums/ServiceRegistryL2ServiceState';
import { TokenSymbol } from '@/enums/Token';
import { Wallets, WalletType } from '@/enums/Wallet';
import { useServices } from '@/hooks/useServices';
import { StakedAgentService } from '@/service/agents/StakedAgentService';
import { Address } from '@/types/Address';
import { WalletAddressNumberRecord } from '@/types/Records';

import { OnlineStatusContext } from './OnlineStatusProvider';
import { WalletContext } from './WalletProvider';

export const BalanceContext = createContext<{
  isLoaded: boolean;
  setIsLoaded: Dispatch<SetStateAction<boolean>>;
  isBalanceLoaded: boolean;
  olasBondBalance?: number;
  olasDepositBalance?: number;
  masterEoaBalance?: ValueOf<WalletAddressNumberRecord>;
  masterSafeBalance?: ValueOf<WalletAddressNumberRecord>;
  totalEthBalance?: number;
  totalOlasBalance?: number;
  isLowBalance: boolean;
  wallets?: Wallets[];
  walletBalances: WalletAddressNumberRecord;
  agentSafeBalance?: ValueOf<WalletAddressNumberRecord>;
  agentEoaBalance?: ValueOf<WalletAddressNumberRecord>;
  updateBalances: () => Promise<void>;
  setIsPaused: Dispatch<SetStateAction<boolean>>;
  totalOlasStakedBalance?: number;
}>({
  isLoaded: false,
  setIsLoaded: () => {},
  isBalanceLoaded: false,
  olasBondBalance: undefined,
  olasDepositBalance: undefined,
  totalEthBalance: undefined,
  totalOlasBalance: undefined,
  isLowBalance: false,
  wallets: undefined,
  walletBalances: {},
  agentSafeBalance: undefined,
  agentEoaBalance: undefined,
  updateBalances: async () => {},
  setIsPaused: () => {},
  totalOlasStakedBalance: undefined,
});

export const BalanceProvider = ({ children }: PropsWithChildren) => {
  const { isOnline } = useContext(OnlineStatusContext);
  const { wallets } = useContext(WalletContext);
  const { services, serviceAddresses } = useServices();
  // const { optimisticRewardsEarnedForEpoch, accruedServiceStakingRewards } =
  //   useContext(RewardContext);

  const [isLoaded, setIsLoaded] = useState<boolean>(false);
  const [isPaused, setIsPaused] = useState<boolean>(false);

  const [isBalanceLoaded, setIsBalanceLoaded] = useState<boolean>(false);

  const [walletBalances, setWalletBalances] = useState<BalanceResult[]>([]);

  // // TODO: refactor to support multiple chains, and gas tokens from config
  // const totalEthBalance: number | undefined = useMemo(() => {
  //   if (!isLoaded) return;
  //   return Object.values(walletBalances).reduce(
  //     (acc: number, walletBalance) => acc + walletBalance.ETH,
  //     0,
  //   );
  // }, [isLoaded, walletBalances]);

  // const totalOlasBalance: number | undefined = useMemo(() => {
  //   if (!isLoaded) return;

  //   const sumWalletBalances = Object.values(walletBalances).reduce(
  //     (acc: number, walletBalance) => acc + walletBalance.OLAS,
  //     0,
  //   );

  //   const total =
  //     sumWalletBalances +
  //     (olasDepositBalance ?? 0) +
  //     (olasBondBalance ?? 0) +
  //     (optimisticRewardsEarnedForEpoch ?? 0) +
  //     (accruedServiceStakingRewards ?? 0);

  //   return total;
  // }, [accruedServiceStakingRewards, isLoaded, optimisticRewardsEarnedForEpoch]);

  // const totalOlasStakedBalance: number | undefined = useMemo(() => {
  //   if (!isLoaded) return;
  //   return (olasBondBalance ?? 0) + (olasDepositBalance ?? 0);
  // }, [isLoaded, olasBondBalance, olasDepositBalance]);

  const updateBalances = useCallback(async (): Promise<void> => {
    if (!wallets) return;

    const walletBalances = await getCrossChainWalletBalances(wallets);
    setWalletBalances(walletBalances);

    try {
      // TODO: refactor to use ChainId enum, service from useService(),
      const serviceId =
        services?.[0]?.chain_configs[CHAIN_CONFIG.OPTIMISM.chainId].chain_data
          .token;

      if (
        !isNil(masterSafeAddress) &&
        isAddress(masterSafeAddress) &&
        serviceId > 0
      ) {
        const { depositValue, bondValue, serviceState } =
          await StakedAgentService.getServiceRegistryInfo(
            masterSafeAddress,
            serviceId,
            ChainId.Gnosis, // TODO: refactor to get chain id from service
          );

        switch (serviceState) {
          case ServiceRegistryL2ServiceState.NonExistent:
            setOlasBondBalance(0);
            setOlasDepositBalance(0);
            break;
          case ServiceRegistryL2ServiceState.PreRegistration:
            setOlasBondBalance(0);
            setOlasDepositBalance(0);
            break;
          case ServiceRegistryL2ServiceState.ActiveRegistration:
            setOlasBondBalance(0);
            setOlasDepositBalance(depositValue);
            break;
          case ServiceRegistryL2ServiceState.FinishedRegistration:
            setOlasBondBalance(bondValue);
            setOlasDepositBalance(depositValue);
            break;
          case ServiceRegistryL2ServiceState.Deployed:
            setOlasBondBalance(bondValue);
            setOlasDepositBalance(depositValue);
            break;
          case ServiceRegistryL2ServiceState.TerminatedBonded:
            setOlasBondBalance(bondValue);
            setOlasDepositBalance(0);
            break;
        }
      }

      // update balance loaded state
      setIsLoaded(true);
      setIsBalanceLoaded(true);
    } catch (error) {
      console.error(error);
      message.error('Unable to retrieve wallet balances');
      setIsBalanceLoaded(true);
    }
  }, [serviceAddresses, services, wallets]);

  const isLowBalance = useMemo(() => {
    if (!masterSafeBalance || !agentSafeBalance) return false;
    if (
      masterSafeBalance.ETH < LOW_MASTER_SAFE_BALANCE &&
      // Need to check agentSafe balance as well, because it's auto-funded from safeBalance
      agentSafeBalance.ETH < LOW_AGENT_SAFE_BALANCE
    )
      return true;
    return false;
  }, [masterSafeBalance, agentSafeBalance]);

  useInterval(
    () => {
      updateBalances();
    },
    isPaused || !isOnline ? null : FIVE_SECONDS_INTERVAL,
  );

  return (
    <BalanceContext.Provider
      value={{
        isLoaded,
        setIsLoaded,
        isBalanceLoaded,
        olasBondBalance,
        olasDepositBalance,
        isLowBalance,
        wallets,
        walletBalances,
        updateBalances,
        setIsPaused,
        totalOlasStakedBalance,
      }}
    >
      {children}
    </BalanceContext.Provider>
  );
};

type BalanceResult = {
  walletAddress: Address;
  chainId: ChainId;
  symbol: TokenSymbol;
  isNative: boolean;
  balance: BigNumberish;
};

const getCrossChainWalletBalances = async (
  wallets: Wallets,
): Promise<BalanceResult[]> => {
  const providerEntries = Object.entries(PROVIDERS);

  // Get balances for each chain
  const balanceResults = await Promise.allSettled(
    providerEntries.map(
      async ([chainIdKey, { multicallProvider: chainMulticallProvider }]) => {
        const chainId = +chainIdKey as ChainId;

        // Get tokens for this chain
        const tokens = TOKEN_CONFIG[chainId];
        if (!tokens) return [] as BalanceResult[];

        // Create balance checking promises for all tokens and wallets
        const chainBalancePromises: Promise<BalanceResult[]>[] = Object.entries(
          tokens,
        ).map(async ([symbolKey, tokenConfig]) => {
          const symbol = symbolKey as TokenSymbol;

          const results: BalanceResult[] = [];
          const isNative = tokenConfig.tokenType === TokenType.NativeGas;
          const isErc20 = tokenConfig.tokenType === TokenType.Erc20;

          // Filter relevant wallets
          const relevantWallets = wallets.filter((wallet) => {
            const isEoa = wallet.type === WalletType.EOA;
            const isSafe = wallet.type === WalletType.Safe;
            const isOnSameChain = isEoa || wallet.chainId === chainId;
            return isEoa || (isSafe && isOnSameChain);
          });

          if (isNative) {
            // Handle native token balances
            const nativeBalances = await Promise.all(
              relevantWallets.map(async (wallet) => {
                const balance = await chainMulticallProvider.getEthBalance(
                  wallet.address,
                );
                return {
                  walletAddress: wallet.address,
                  chainId,
                  symbol,
                  isNative: true,
                  balance,
                } as BalanceResult;
              }),
            );
            results.push(...nativeBalances);
          }

          if (isErc20) {
            // Create ERC20 contract interface for multicall
            const erc20Contract = new MulticallContract(
              tokenConfig.address,
              ERC20_BALANCE_OF_STRING_FRAGMENT,
            );

            // Prepare multicall for ERC20 balances
            const erc20Calls = relevantWallets.map((wallet) =>
              erc20Contract.balanceOf(wallet.address),
            );

            // Execute multicall
            const erc20Balances = await chainMulticallProvider.all(erc20Calls);

            // Map results to balance objects
            const erc20Results = relevantWallets.map((wallet, index) => ({
              walletAddress: wallet.address,
              chainId,
              symbol,
              isNative: false,
              balance: erc20Balances[index],
            })) as BalanceResult[];

            results.push(...erc20Results);
          }

          return results;
        });

        // Wait for all token balance promises to resolve and handle results
        const chainResults = await Promise.allSettled(chainBalancePromises);

        // Filter and flatten successful results
        return chainResults
          .filter(
            (result): result is PromiseFulfilledResult<BalanceResult[]> =>
              result.status === 'fulfilled',
          )
          .map((result) => result.value)
          .flat();
      },
    ),
  );

  // Filter and flatten successful results from all chains
  return balanceResults
    .filter(
      (result): result is PromiseFulfilledResult<BalanceResult[]> =>
        result.status === 'fulfilled',
    )
    .map((result) => result.value)
    .flat();
};

// TODO: implement staked balances cross-chain for all master safes

// const getCrossChainStakedBalances = async (
//   wallets: MasterSafe[],
// ): Promise<{
//   olasBondBalance?: number;
//   olasDepositBalance?: number;
// }>[] => ({});
