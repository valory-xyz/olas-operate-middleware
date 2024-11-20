import { Contract as MulticallContract } from 'ethers-multicall';
import {
  createContext,
  Dispatch,
  PropsWithChildren,
  SetStateAction,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import { useInterval } from 'usehooks-ts';

import { ERC20_BALANCE_OF_STRING_FRAGMENT } from '@/abis/erc20';
import { MiddlewareServiceResponse } from '@/client';
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
import { WalletOwnerType, Wallets, WalletType } from '@/enums/Wallet';
import { useServices } from '@/hooks/useServices';
import {
  GetServiceRegistryInfoResponse,
  StakedAgentService,
} from '@/service/agents/StakedAgentService';
import { Address } from '@/types/Address';
import { formatEther } from '@/utils/numberFormatters';

import { OnlineStatusContext } from './OnlineStatusProvider';
import { WalletContext } from './WalletProvider';

export const BalanceContext = createContext<{
  isLoaded: boolean;
  setIsLoaded: Dispatch<SetStateAction<boolean>>;
  updateBalances: () => Promise<void>;
  setIsPaused: Dispatch<SetStateAction<boolean>>;
  walletBalances: WalletBalanceResult[];
  stakedBalances?: CrossChainStakedBalances;
  totalOlasBalance?: number;
  totalEthBalance?: number;
  totalStakedOlasBalance?: number;
  lowBalances?: {
    serviceConfigId: string;
    chainId: ChainId;
    walletAddress: Address;
    balance: number;
    expectedBalance: number;
  }[];
  isPaused: boolean;
}>({
  isLoaded: false,
  setIsLoaded: () => {},
  updateBalances: async () => {},
  isPaused: false,
  setIsPaused: () => {},
  walletBalances: [],
  stakedBalances: {},
  totalOlasBalance: 0,
  totalEthBalance: 0,
  totalStakedOlasBalance: 0,
  lowBalances: [],
});

export const BalanceProvider = ({ children }: PropsWithChildren) => {
  const { isOnline } = useContext(OnlineStatusContext);
  const { wallets } = useContext(WalletContext);
  const { services } = useServices();
  // const { optimisticRewardsEarnedForEpoch, accruedServiceStakingRewards } =
  //   useContext(RewardContext);

  const [isLoaded, setIsLoaded] = useState<boolean>(false);
  const [isPaused, setIsPaused] = useState<boolean>(false);
  const [isUpdatingBalances, setIsUpdatingBalances] = useState<boolean>(false);

  const [walletBalances, setWalletBalances] = useState<WalletBalanceResult[]>(
    [],
  );
  const [stakedBalances, setStakedBalances] =
    useState<CrossChainStakedBalances>();

  const totalEthBalance = useMemo(() => {
    if (!isLoaded) return;
    return walletBalances.reduce((acc, walletBalance) => {
      if (walletBalance.isNative) {
        return acc + walletBalance.balance;
      }
      return acc;
    }, 0);
  }, [isLoaded, walletBalances]);

  const totalOlasBalance = useMemo(() => {
    if (!isLoaded) return;
    return walletBalances.reduce((acc, walletBalance) => {
      if (walletBalance.symbol === TokenSymbol.OLAS) {
        return acc + walletBalance.balance;
      }
      return acc;
    }, 0);
  }, [isLoaded, walletBalances]);

  const totalStakedOlasBalance = useMemo(() => {
    if (!stakedBalances) return 0;

    return Object.values(stakedBalances).reduce(
      (serviceAcc, serviceBalances) => {
        return (
          serviceAcc +
          Object.values(serviceBalances).reduce((chainAcc, chainBalance) => {
            return (
              chainAcc +
              (chainBalance.olasBondBalance || 0) +
              (chainBalance.olasDepositBalance || 0)
            );
          }, 0)
        );
      },
      0,
    );
  }, [stakedBalances]);

  /**
   * An array of wallet address that have low native token balances
   */
  const lowBalanceWalletAddresses = useMemo<
    {
      serviceConfigId: string;
      chainId: ChainId;
      walletAddress: Address;
      balance: number;
      expectedBalance: number;
    }[]
  >(() => {
    const result = [];

    for (const service of services ?? []) {
      const serviceId = service.service_config_id;
      const serviceHomeChainId = service.home_chain_id;
      const serviceStakedBalances = stakedBalances?.[serviceId];
      if (!serviceStakedBalances) continue;

      // get addresses for master safe and agent home chain safe

      const masterSafeAddress = wallets?.find(
        (wallet) =>
          wallet.owner === WalletOwnerType.Master &&
          wallet.type === WalletType.Safe &&
          wallet.chainId === service.home_chain_id,
      );

      const stakedAgentSafeAddress =
        service.chain_configs[serviceHomeChainId].chain_data.multisig;

      // skip invalid service
      if (!masterSafeAddress && !stakedAgentSafeAddress) continue;

      // balances
      const masterSafeBalanceResult = walletBalances.find(
        (balance) =>
          balance.walletAddress === masterSafeAddress?.address &&
          balance.isNative,
      );

      const stakedAgentSafeBalanceResult = walletBalances.find(
        (balance) =>
          balance.walletAddress === stakedAgentSafeAddress && balance.isNative,
      );

      if (
        masterSafeBalanceResult &&
        masterSafeBalanceResult?.balance < LOW_MASTER_SAFE_BALANCE // TODO: use agent specific threshold
      ) {
        result.push({
          serviceConfigId: service.service_config_id,
          chainId: serviceHomeChainId,
          walletAddress: masterSafeBalanceResult.walletAddress,
          balance: masterSafeBalanceResult.balance,
          expectedBalance: LOW_MASTER_SAFE_BALANCE,
        });
      }

      if (
        stakedAgentSafeBalanceResult &&
        stakedAgentSafeBalanceResult?.balance < LOW_AGENT_SAFE_BALANCE //TODO: use agent specific threshold
      ) {
        result.push({
          serviceConfigId: service.service_config_id,
          chainId: serviceHomeChainId,
          walletAddress: stakedAgentSafeBalanceResult.walletAddress,
          balance: stakedAgentSafeBalanceResult.balance,
          expectedBalance: LOW_AGENT_SAFE_BALANCE,
        });
      }
    }

    return result;
  }, [services, stakedBalances, wallets, walletBalances]);

  const updateBalances = useCallback(async () => {
    if (wallets && services) {
      setIsUpdatingBalances(true);

      await Promise.allSettled([
        getCrossChainWalletBalances(wallets).then((balances) => {
          setWalletBalances(balances);
          setIsLoaded(true);
        }),
        getCrossChainStakedBalances(services).then((balances) => {
          setStakedBalances(balances);
        }),
      ])
        .then(() => setIsLoaded(true))
        .finally(() => setIsUpdatingBalances(false));
    }
  }, [services, wallets]);

  useEffect(() => {
    // update balances once on load, then use interval
    if (!isOnline) return;
    if (isUpdatingBalances || isLoaded) return;

    updateBalances();
  }, [isLoaded, isOnline, isUpdatingBalances, updateBalances]);

  useInterval(updateBalances, FIVE_SECONDS_INTERVAL);

  return (
    <BalanceContext.Provider
      value={{
        isLoaded,
        setIsLoaded,
        walletBalances,
        stakedBalances,
        updateBalances,
        isPaused,
        setIsPaused,
        totalOlasBalance,
        totalEthBalance,
        totalStakedOlasBalance,
        lowBalances: lowBalanceWalletAddresses,
      }}
    >
      {children}
    </BalanceContext.Provider>
  );
};

type WalletBalanceResult = {
  walletAddress: Address;
  chainId: ChainId;
  symbol: TokenSymbol;
  isNative: boolean;
  balance: number;
};

const getCrossChainWalletBalances = async (
  wallets: Wallets,
): Promise<WalletBalanceResult[]> => {
  const providerEntries = Object.entries(PROVIDERS);

  // Get balances for each chain
  const balanceResults = await Promise.allSettled(
    providerEntries.map(
      async ([chainIdKey, { multicallProvider: chainMulticallProvider }]) => {
        const chainId = +chainIdKey as ChainId;

        // Get tokens for this chain
        const tokens = TOKEN_CONFIG[chainId];
        if (!tokens) return [] as WalletBalanceResult[];

        // Create balance checking promises for all tokens and wallets
        const chainBalancePromises: Promise<WalletBalanceResult[]>[] =
          Object.entries(tokens).map(async ([symbolKey, tokenConfig]) => {
            const symbol = symbolKey as TokenSymbol;

            const results: WalletBalanceResult[] = [];
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
                    balance: +formatEther(balance),
                  } as WalletBalanceResult;
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
              const erc20Balances =
                await chainMulticallProvider.all(erc20Calls);

              // Map results to balance objects
              const erc20Results = relevantWallets.map((wallet, index) => ({
                walletAddress: wallet.address,
                chainId,
                symbol,
                isNative: false,
                balance: erc20Balances[index],
              })) as WalletBalanceResult[];

              results.push(...erc20Results);
            }

            return results;
          });

        // Wait for all token balance promises to resolve and handle results
        const chainResults = await Promise.allSettled(chainBalancePromises);

        // Filter and flatten successful results
        return chainResults
          .filter(
            (result): result is PromiseFulfilledResult<WalletBalanceResult[]> =>
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
      (result): result is PromiseFulfilledResult<WalletBalanceResult[]> =>
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
