import { BigNumberish } from 'ethers';
import { Contract as MulticallContract } from 'ethers-multicall';
import {
  createContext,
  Dispatch,
  PropsWithChildren,
  SetStateAction,
  useCallback,
  useContext,
  useEffect,
  useState,
} from 'react';

import { ERC20_BALANCE_OF_STRING_FRAGMENT } from '@/abis/erc20';
import { MiddlewareServiceResponse } from '@/client';
import { TOKEN_CONFIG, TokenType } from '@/config/tokens';
import { PROVIDERS } from '@/constants/providers';
import { ChainId } from '@/enums/Chain';
import { ServiceRegistryL2ServiceState } from '@/enums/ServiceRegistryL2ServiceState';
import { TokenSymbol } from '@/enums/Token';
import { Wallets, WalletType } from '@/enums/Wallet';
import { useServices } from '@/hooks/useServices';
import {
  GetServiceRegistryInfoResponse,
  StakedAgentService,
} from '@/service/agents/StakedAgentService';
import { Address } from '@/types/Address';

import { OnlineStatusContext } from './OnlineStatusProvider';
import { WalletContext } from './WalletProvider';

export const BalanceContext = createContext<{
  isLoaded: boolean;
  setIsLoaded: Dispatch<SetStateAction<boolean>>;
  totalOlasBalance?: number;
  isLowBalance: boolean;
  updateBalances: () => Promise<void>;
  setIsPaused: Dispatch<SetStateAction<boolean>>;
  walletBalances: BalanceResult[];
  stakedBalances: CrossChainStakedBalances;
}>({
  isLoaded: false,
  setIsLoaded: () => {},
  totalOlasBalance: undefined,
  isLowBalance: false,
  updateBalances: async () => {},
  setIsPaused: () => {},
  walletBalances: [],
  stakedBalances: {},
});

export const BalanceProvider = ({ children }: PropsWithChildren) => {
  const { isOnline } = useContext(OnlineStatusContext);
  const { wallets } = useContext(WalletContext);
  const { services } = useServices();
  // const { optimisticRewardsEarnedForEpoch, accruedServiceStakingRewards } =
  //   useContext(RewardContext);

  const [isLoaded, setIsLoaded] = useState<boolean>(false);
  const [isPaused, setIsPaused] = useState<boolean>(false);

  const [walletBalances, setWalletBalances] = useState<BalanceResult[]>([]);
  const [stakedBalances, setStakedBalances] =
    useState<CrossChainStakedBalances>();

  const updateBalances = useCallback(async () => {
    if (wallets && services) {
      getCrossChainWalletBalances(wallets).then((balances) => {
        setWalletBalances(balances);
        setIsLoaded(true);
      });

      getCrossChainStakedBalances(services).then((balances) => {
        setStakedBalances(balances);
      });
    }
  }, [services, wallets]);

  useEffect(() => {
    if (!isLoaded) updateBalances();
  }, [isLoaded, updateBalances]);

  // // TODO: refactor to parse `walletbalances`

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
  // }, [isLoaded]);

  // // TODO: include in walletBalances
  // // const isLowBalance = useMemo(() => {
  // //   if (!masterSafeBalance || !agentSafeBalance) return false;
  // //   if (
  // //     masterSafeBalance.ETH < LOW_MASTER_SAFE_BALANCE &&
  // //     // Need to check agentSafe balance as well, because it's auto-funded from safeBalance
  // //     agentSafeBalance.ETH < LOW_AGENT_SAFE_BALANCE
  // //   )
  // //     return true;
  // //   return false;
  // // }, [masterSafeBalance, agentSafeBalance]);

  // useInterval(
  //   () => {
  //     updateBalances();
  //   },
  //   isPaused || !isOnline ? null : FIVE_SECONDS_INTERVAL,
  // );

  return (
    <BalanceContext.Provider
      value={{
        isLoaded,
        setIsLoaded,
        walletBalances,
        stakedBalances: stakedBalances || {},
        updateBalances,
        setIsPaused,
        isLowBalance: false,
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

type CrossChainStakedBalances = {
  [serviceId: string]: {
    [chainId: number]: {
      olasBondBalance: number;
      olasDepositBalance: number;
    };
  };
};

const getCrossChainStakedBalances = async (
  services: MiddlewareServiceResponse[],
): Promise<CrossChainStakedBalances> => {
  const result: CrossChainStakedBalances = {};

  // for each service, create a nest objects for chain staked balances
  const registryInfoCalls: Promise<GetServiceRegistryInfoResponse>[] = [];
  services.forEach((service) => {
    const homeChainId = service.home_chain_id;
    const homeChainConfig = service.chain_configs[homeChainId];
    const { multisig, token } = homeChainConfig.chain_data;

    if (!multisig || !token) {
      registryInfoCalls.push(
        Promise.resolve({
          depositValue: 0,
          bondValue: 0,
          serviceState: ServiceRegistryL2ServiceState.NonExistent,
        }),
      );
      return;
    }

    registryInfoCalls.push(
      StakedAgentService.getServiceRegistryInfo(multisig, token, homeChainId),
    );
  });

  // TODO: chunk and batch multicalls by chain,
  // currently Promise is returned by `StakedAgentService.getServiceRegistryInfo`
  // will not scale well with large number of services
  const registryInfos = await Promise.allSettled(registryInfoCalls);

  registryInfos.forEach((res, index) => {
    if (res.status === 'fulfilled') {
      const { depositValue, bondValue, serviceState } =
        res.value as GetServiceRegistryInfoResponse;
      const serviceId = services[index].service_config_id;
      const homeChainId = services[index].home_chain_id;

      if (!result[serviceId]) result[serviceId] = {};
      if (!result[serviceId][homeChainId])
        result[serviceId][homeChainId] = {
          olasBondBalance: 0,
          olasDepositBalance: 0,
        };

      // service state is used to determine the correct bond and deposit balances
      // stops funds from being displayed incorrectly during service state transitions
      const serviceStateBondDepositBalances = correctBondDepositByServiceState({
        olasBondBalance: bondValue,
        olasDepositBalance: depositValue,
        serviceState,
      });

      result[serviceId][homeChainId] = serviceStateBondDepositBalances;
    }
  });

  return result;
};

/**
 * Corrects the bond and deposit balances based on the service state
 * @note the service state is used to determine the correct bond and deposit balances
 */
const correctBondDepositByServiceState = ({
  olasBondBalance,
  olasDepositBalance,
  serviceState,
}: {
  olasBondBalance: number;
  olasDepositBalance: number;
  serviceState: ServiceRegistryL2ServiceState;
}): {
  olasBondBalance: number;
  olasDepositBalance: number;
} => {
  switch (serviceState) {
    case ServiceRegistryL2ServiceState.NonExistent:
      return {
        olasBondBalance: 0,
        olasDepositBalance: 0,
      };
    case ServiceRegistryL2ServiceState.PreRegistration:
      return {
        olasBondBalance: 0,
        olasDepositBalance: 0,
      };
    case ServiceRegistryL2ServiceState.ActiveRegistration:
      return {
        olasBondBalance: 0,
        olasDepositBalance,
      };
    case ServiceRegistryL2ServiceState.FinishedRegistration:
      return {
        olasBondBalance,
        olasDepositBalance,
      };
    case ServiceRegistryL2ServiceState.Deployed:
      return {
        olasBondBalance,
        olasDepositBalance,
      };
    case ServiceRegistryL2ServiceState.TerminatedBonded:
      return {
        olasBondBalance,
        olasDepositBalance: 0,
      };
    default:
      throw new Error('Invalid service state');
  }
};
