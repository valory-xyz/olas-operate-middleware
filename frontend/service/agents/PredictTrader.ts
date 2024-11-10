import { BigNumber, ethers } from 'ethers';
import { formatEther } from 'ethers/lib/utils';

import {
  STAKING_PROGRAMS,
  StakingProgramConfig,
} from '@/config/stakingPrograms';
import { PROVIDERS } from '@/constants/providers';
import { ChainId } from '@/enums/Chain';
import { StakingProgramId } from '@/enums/StakingProgram';
import { Address } from '@/types/Address';
import { StakingContractInfo, StakingRewardsInfo } from '@/types/Autonolas';

import { StakedAgentService } from './StakedAgentService';

const MECH_REQUESTS_SAFETY_MARGIN = 1;

export abstract class PredictTraderService extends StakedAgentService {
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

    const [, stakingProgramConfig] = Object.entries(STAKING_PROGRAMS).find(
      ([entryKey]) => entryKey === stakingProgramId,
    ) as [unknown, StakingProgramConfig];

    if (!stakingProgramConfig) throw new Error('Staking program not found');

    const {
      activityChecker,
      contract: stakingTokenProxyContract,
      chainId,
    } = stakingProgramConfig;

    const provider = PROVIDERS[chainId].multicallProvider;

    const contractCalls = [
      // mechContract.getRequestsCount(agentMultisigAddress),
      stakingTokenProxyContract.getServiceInfo(serviceId),
      stakingTokenProxyContract.livenessPeriod(),
      activityChecker.livenessRatio(),
      stakingTokenProxyContract.rewardsPerSecond(),
      stakingTokenProxyContract.calculateStakingReward(serviceId),
      stakingTokenProxyContract.minStakingDeposit(),
      stakingTokenProxyContract.tsCheckpoint(),
    ];

    const multicallResponse = await provider.all(contractCalls);

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
      MECH_REQUESTS_SAFETY_MARGIN;

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
    const stakingTokenProxy = STAKING_PROGRAMS[stakingProgramId].contract;
    const provider = PROVIDERS[ChainId.Gnosis].multicallProvider;

    const contractCalls = [
      stakingTokenProxy.rewardsPerSecond(),
      stakingTokenProxy.livenessPeriod(), // epoch length
      stakingTokenProxy.tsCheckpoint(), // last checkpoint timestamp
    ];

    const multicallResponse = await provider.all(contractCalls);
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
    const stakingTokenProxy = STAKING_PROGRAMS[stakingProgramId].contract;

    const contractCalls = [
      stakingTokenProxy.availableRewards(),
      stakingTokenProxy.maxNumServices(),
      stakingTokenProxy.getServiceIds(),
      stakingTokenProxy.minStakingDuration(),
      stakingTokenProxy.getServiceInfo(serviceId),
      stakingTokenProxy.getStakingState(serviceId),
      stakingTokenProxy.minStakingDeposit(),
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
    stakingProgramId: StakingProgramId,
  ): Promise<Partial<StakingContractInfo>> => {
    const stakingContract =
      STAKING_PROGRAMS[StakingProgramId][stakingProgramId];

    const contractCalls = [
      stakingTokenProxyContracts[stakingProgramId].availableRewards(),
      stakingTokenProxyContracts[stakingProgramId].maxNumServices(),
      stakingTokenProxyContracts[stakingProgramId].getServiceIds(),
      stakingTokenProxyContracts[stakingProgramId].minStakingDuration(),
      stakingTokenProxyContracts[stakingProgramId].minStakingDeposit(),
      stakingTokenProxyContracts[stakingProgramId].rewardsPerSecond(),
      stakingTokenProxyContracts[stakingProgramId].numAgentInstances(),
      stakingTokenProxyContracts[stakingProgramId].livenessPeriod(),
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
}
