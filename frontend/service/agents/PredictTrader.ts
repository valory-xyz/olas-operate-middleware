import { BigNumber, ethers } from 'ethers';
import { formatEther } from 'ethers/lib/utils';
import { Contract } from 'ethers-multicall';

import { ContractParams, CONTRACTS } from '@/config/contracts';
import { STAKING_PROGRAMS } from '@/config/stakingPrograms';
import { PROVIDERS } from '@/constants/providers';
import { ChainId } from '@/enums/Chain';
import { ContractType } from '@/enums/Contract';
import { ServiceRegistryL2ServiceState } from '@/enums/ServiceRegistryL2ServiceState';
import { StakingProgramId } from '@/enums/StakingProgram';
import { Address } from '@/types/Address';
import { StakingContractInfo, StakingRewardsInfo } from '@/types/Autonolas';

import { AgentServiceApi } from './Agent';

export abstract class PredictTraderServiceApi extends AgentServiceApi {
  static getAgentStakingRewardsInfo = async ({
    agentMultisigAddress,
    serviceId,
    stakingProgramId,
  }: {
    agentMultisigAddress: Address;
    serviceId: number;
    stakingProgramId: string;
  }): Promise<StakingRewardsInfo | undefined> => {
    if (!agentMultisigAddress) return;
    if (!serviceId) return;

    const stakingProgramConfig = Object.entries(STAKING_PROGRAMS)
      .filter(([chainIdKey, stakingProgram]) => chainIdKey === chainId)
      .find((stakingProgram) => stakingProgram === stakingProgramId);

    if (!stakingProgramConfig) throw new Error('Staking program not found');

    const mechContractConfig = contractConfig[
      stakingProgramConfig.supportedMech
    ] as ContractParams;

    if (!mechContractConfig) throw new Error('Mech contract not found');

    const mechContract = new Contract(
      mechContractConfig.address,
      mechContractConfig.abi,
    );

    // stakingProgram === StakingProgramId.BetaMechMarketplace
    //   ? mechMarketplaceContract
    //   : agentMechContract;

    const activityCheckerContract = stakingActivityCheckerContract;
    // stakingProgram === StakingProgramId.BetaMechMarketplace
    //   ? mechMarketplaceActivityCheckerContract
    //   : agentMechActivityCheckerContract;

    const contractCalls = [
      // mechContract.getRequestsCount(agentMultisigAddress),
      stakingTokenProxyContracts[stakingProgramId].getServiceInfo(serviceId),
      stakingTokenProxyContracts[stakingProgramId].livenessPeriod(),
      activityCheckerContract.livenessRatio(),
      stakingTokenProxyContracts[stakingProgramId].rewardsPerSecond(),
      stakingTokenProxyContracts[stakingProgramId].calculateStakingReward(
        serviceId,
      ),
      stakingTokenProxyContracts[stakingProgramId].minStakingDeposit(),
      stakingTokenProxyContracts[stakingProgramId].tsCheckpoint(),
    ];

    const multicallResponse =
      await OPTIMISM_MULTICALL_PROVIDER.all(contractCalls);

    const [
      mechRequestCount,
      serviceInfo,
      livenessPeriod,
      livenessRatio,
      rewardsPerSecond,
      accruedStakingReward,
      minStakingDeposit,
      tsCheckpoint,
    ] = multicallResponse;

    /**
     * struct ServiceInfo {
      // Service multisig address
      address multisig;
      // Service owner
      address owner;
      // Service multisig nonces
      uint256[] nonces; <-- (we use this in the rewards eligibility check)
      // Staking start time
      uint256 tsStart;
      // Accumulated service staking reward
      uint256 reward;
      // Accumulated inactivity that might lead to the service eviction
      uint256 inactivity;}
     */

    const nowInSeconds = Math.floor(Date.now() / 1000);

    const requiredMechRequests =
      (Math.ceil(Math.max(livenessPeriod, nowInSeconds - tsCheckpoint)) *
        livenessRatio) /
        1e18 +
      REQUIRED_MECH_REQUESTS_SAFETY_MARGIN;

    const mechRequestCountOnLastCheckpoint = serviceInfo[2][1];
    const eligibleRequests =
      mechRequestCount - mechRequestCountOnLastCheckpoint;

    const isEligibleForRewards = eligibleRequests >= requiredMechRequests;

    const availableRewardsForEpoch = Math.max(
      rewardsPerSecond * livenessPeriod, // expected rewards for the epoch
      rewardsPerSecond * (nowInSeconds - tsCheckpoint), // incase of late checkpoint
    );

    // Minimum staked amount is double the minimum staking deposit
    // (all the bonds must be the same as deposit)
    const minimumStakedAmount =
      parseFloat(ethers.utils.formatEther(`${minStakingDeposit}`)) * 2;

    return {
      // mechRequestCount,
      serviceInfo,
      livenessPeriod,
      livenessRatio,
      rewardsPerSecond,
      isEligibleForRewards,
      availableRewardsForEpoch,
      accruedServiceStakingRewards: parseFloat(
        ethers.utils.formatEther(`${accruedStakingReward}`),
      ),
      minimumStakedAmount,
    } as StakingRewardsInfo;
  };

  static getAvailableRewardsForEpoch = async (
    stakingProgramId: StakingProgramId,
  ): Promise<number | undefined> => {
    return 0;

    const contractCalls = [
      stakingTokenProxyContracts[stakingProgramId].rewardsPerSecond(),
      stakingTokenProxyContracts[stakingProgramId].livenessPeriod(), // epoch length
      stakingTokenProxyContracts[stakingProgramId].tsCheckpoint(), // last checkpoint timestamp
    ];

    const multicallResponse =
      await OPTIMISM_MULTICALL_PROVIDER.all(contractCalls);
    const [rewardsPerSecond, livenessPeriod, tsCheckpoint] = multicallResponse;
    const nowInSeconds = Math.floor(Date.now() / 1000);

    return Math.max(
      rewardsPerSecond * livenessPeriod, // expected rewards
      rewardsPerSecond * (nowInSeconds - tsCheckpoint), // incase of late checkpoint
    );
  };

  static getStakingContractInfoByServiceIdStakingProgram = async (
    serviceId: number,
    stakingProgramId: StakingProgramId,
  ): Promise<Partial<StakingContractInfo> | undefined> => {
    if (!serviceId) return;

    const contractCalls = [
      stakingTokenProxyContracts[stakingProgramId].availableRewards(),
      stakingTokenProxyContracts[stakingProgramId].maxNumServices(),
      stakingTokenProxyContracts[stakingProgramId].getServiceIds(),
      stakingTokenProxyContracts[stakingProgramId].minStakingDuration(),
      stakingTokenProxyContracts[stakingProgramId].getServiceInfo(serviceId),
      stakingTokenProxyContracts[stakingProgramId].getStakingState(serviceId),
      stakingTokenProxyContracts[stakingProgramId].minStakingDeposit(),
    ];

    const multicallResponse =
      await OPTIMISM_MULTICALL_PROVIDER.all(contractCalls);
    const [
      availableRewardsInBN,
      maxNumServicesInBN,
      getServiceIdsInBN,
      minStakingDurationInBN,
      serviceInfo,
      serviceStakingState,
      minStakingDeposit,
    ] = multicallResponse;

    const availableRewards = parseFloat(
      ethers.utils.formatUnits(availableRewardsInBN, 18),
    );
    const serviceIds = getServiceIdsInBN.map((id: BigNumber) => id.toNumber());
    const maxNumServices = maxNumServicesInBN.toNumber();

    return {
      availableRewards,
      maxNumServices,
      serviceIds,
      minimumStakingDuration: minStakingDurationInBN.toNumber(),
      serviceStakingStartTime: serviceInfo.tsStart.toNumber(),
      serviceStakingState,
      minStakingDeposit: parseFloat(
        ethers.utils.formatEther(minStakingDeposit),
      ),
    };
  };

  /**
   * Get staking contract info by staking program name
   * eg. Alpha, Beta, Beta2
   */
  static getStakingContractInfoByStakingProgram = async (
    stakingProgram: StakingProgramId,
  ): Promise<Partial<StakingContractInfo>> => {
    const contractCalls = [
      stakingTokenProxyContracts[stakingProgram].availableRewards(),
      stakingTokenProxyContracts[stakingProgram].maxNumServices(),
      stakingTokenProxyContracts[stakingProgram].getServiceIds(),
      stakingTokenProxyContracts[stakingProgram].minStakingDuration(),
      stakingTokenProxyContracts[stakingProgram].minStakingDeposit(),
      stakingTokenProxyContracts[stakingProgram].rewardsPerSecond(),
      stakingTokenProxyContracts[stakingProgram].numAgentInstances(),
      stakingTokenProxyContracts[stakingProgram].livenessPeriod(),
    ];

    const multicallResponse =
      await OPTIMISM_MULTICALL_PROVIDER.all(contractCalls);
    const [
      availableRewardsInBN,
      maxNumServicesInBN,
      getServiceIdsInBN,
      minStakingDurationInBN,
      minStakingDeposit,
      rewardsPerSecond,
      numAgentInstances,
      livenessPeriod,
    ] = multicallResponse;

    const availableRewards = parseFloat(
      ethers.utils.formatUnits(availableRewardsInBN, 18),
    );

    const serviceIds = getServiceIdsInBN.map((id: BigNumber) => id.toNumber());
    const maxNumServices = maxNumServicesInBN.toNumber();

    // APY
    const rewardsPerYear = rewardsPerSecond.mul(ONE_YEAR);

    let apy = 0;

    if (rewardsPerSecond.gt(0) && minStakingDeposit.gt(0)) {
      apy =
        Number(rewardsPerYear.mul(100).div(minStakingDeposit)) /
        (1 + numAgentInstances.toNumber());
    }

    // Amount of OLAS required for Stake
    const stakeRequiredInWei = minStakingDeposit.add(
      minStakingDeposit.mul(numAgentInstances),
    );

    const olasStakeRequired = Number(formatEther(stakeRequiredInWei));

    // Rewards per work period
    const rewardsPerWorkPeriod =
      Number(formatEther(rewardsPerSecond as BigNumber)) *
      livenessPeriod.toNumber();

    return {
      availableRewards,
      maxNumServices,
      serviceIds,
      minimumStakingDuration: minStakingDurationInBN.toNumber(),
      minStakingDeposit: parseFloat(
        ethers.utils.formatEther(minStakingDeposit),
      ),
      apy,
      olasStakeRequired,
      rewardsPerWorkPeriod,
    };
  };

  /**
   * Gets service registry info, including:
   * - bondValue
   * - depositValue
   * - serviceState
   */
  static getServiceRegistryInfo = async (
    address: Address, // generally masterSafeAddress
    serviceId: number,
    chainId: ChainId,
  ): Promise<{
    bondValue: number;
    depositValue: number;
    serviceState: ServiceRegistryL2ServiceState;
  }> => {
    if (!CONTRACTS[chainId]) {
      throw new Error('Chain not supported');
    }

    const { serviceRegistryTokenUtilityContract, serviceRegistryL2Contract } =
      CONTRACTS[chainId];

    const contractCalls = [
      serviceRegistryTokenUtilityContract.getOperatorBalance(
        address,
        serviceId,
      ),
      serviceRegistryTokenUtilityContract.mapServiceIdTokenDeposit(serviceId),
      serviceRegistryL2Contract.mapServices(serviceId),
    ];

    const [
      getOperatorBalanceReponse,
      mapServiceIdTokenDepositResponse,
      mapServicesResponse,
    ] = await CONTRACTS[chainId][ContractType.Multicall3].all(contractCalls);

    const [bondValue, depositValue, serviceState] = [
      parseFloat(ethers.utils.formatUnits(getOperatorBalanceReponse, 18)),
      parseFloat(
        ethers.utils.formatUnits(mapServiceIdTokenDepositResponse[1], 18),
      ),
      mapServicesResponse.state as ServiceRegistryL2ServiceState,
    ];

    return {
      bondValue,
      depositValue,
      serviceState,
    };
  };

  static getCurrentStakingProgramByServiceId = async (
    serviceId: number,
    chainId: ChainId,
  ): Promise<StakingProgramId | null> => {
    try {
      const { multicallProvider } = PROVIDERS[chainId];

      // filter out staking programs that are not on the chain
      const stakingProgramEntries = Object.entries(STAKING_PROGRAMS).filter(
        (entry) => {
          const [, program] = entry;
          return program.chainId === chainId;
        },
      );

      // create contract calls
      const contractCalls = stakingProgramEntries.map((entry) => {
        const [, stakingProgram] = entry;
        return stakingProgram.contract.getStakingState(serviceId);
      });

      // get multicall response
      const multicallResponse = await multicallProvider.all(
        Object.values(contractCalls),
      );

      // find the first staking program that is active
      const activeStakingProgramIndex = multicallResponse.findIndex(Boolean);

      // if no staking program is active, return null
      if (activeStakingProgramIndex === -1) {
        return null;
      }

      // return the staking program id
      return stakingProgramEntries[
        activeStakingProgramIndex
      ][0] as StakingProgramId;
    } catch (error) {
      console.error('Error while getting current staking program', error);
      return null;
    }
  };
}
