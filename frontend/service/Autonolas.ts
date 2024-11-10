import { BigNumber, ethers } from 'ethers';
import { formatEther } from 'ethers/lib/utils';
import { Contract as MulticallContract } from 'ethers-multicall';

import { CONTRACT_CONFIG } from '@/config/contracts';
import { STAKING_PROGRAM_CONFIG as STAKING_PROGRAM_CONFIGS } from '@/config/stakingPrograms';
import { ChainId } from '@/enums/Chain';
import { ServiceRegistryL2ServiceState } from '@/enums/ServiceRegistryL2ServiceState';
import { StakingProgramId } from '@/enums/StakingProgram';
import { Address } from '@/types/Address';
import { StakingContractInfo, StakingRewardsInfo } from '@/types/Autonolas';

const ONE_YEAR = 1 * 24 * 60 * 60 * 365;
const REQUIRED_MECH_REQUESTS_SAFETY_MARGIN = 1;

const getAgentStakingRewardsInfo = async ({
  agentMultisigAddress,
  serviceId,
  stakingProgram,
  chainId,
}: {
  agentMultisigAddress: Address;
  serviceId: number;
  stakingProgram: StakingProgramId;
  chainId: ChainId;
}): Promise<StakingRewardsInfo | undefined> => {
  if (!agentMultisigAddress) return;
  if (!serviceId) return;

  const stakingProgramConfig =
    STAKING_PROGRAM_CONFIGS[chainId as keyof typeof STAKING_PROGRAM_CONFIGS][
      stakingProgram
    ];

  const contractConfig =
    CONTRACT_CONFIG[chainId as keyof typeof CONTRACT_CONFIG];

  // const mechContract = agentMechContract;

  // stakingProgram === StakingProgramId.BetaMechMarketplace
  //   ? mechMarketplaceContract
  //   : agentMechContract;

  const activityCheckerContract = stakingActivityCheckerContract;
  // stakingProgram === StakingProgramId.BetaMechMarketplace
  //   ? mechMarketplaceActivityCheckerContract
  //   : agentMechActivityCheckerContract;

  const contractCalls = [
    // mechContract.getRequestsCount(agentMultisigAddress),
    stakingTokenProxyContracts[stakingProgram].getServiceInfo(serviceId),
    stakingTokenProxyContracts[stakingProgram].livenessPeriod(),
    activityCheckerContract.livenessRatio(),
    stakingTokenProxyContracts[stakingProgram].rewardsPerSecond(),
    stakingTokenProxyContracts[stakingProgram].calculateStakingReward(
      serviceId,
    ),
    stakingTokenProxyContracts[stakingProgram].minStakingDeposit(),
    stakingTokenProxyContracts[stakingProgram].tsCheckpoint(),
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
  const eligibleRequests = mechRequestCount - mechRequestCountOnLastCheckpoint;

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

const getAvailableRewardsForEpoch = async (
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

const getStakingContractInfoByServiceIdStakingProgram = async (
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
    minStakingDeposit: parseFloat(ethers.utils.formatEther(minStakingDeposit)),
  };
};

/**
 * Get staking contract info by staking program name
 * eg. Alpha, Beta, Beta2
 */
const getStakingContractInfoByStakingProgram = async (
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
    minStakingDeposit: parseFloat(ethers.utils.formatEther(minStakingDeposit)),
    apy,
    olasStakeRequired,
    rewardsPerWorkPeriod,
  };
};

const getServiceRegistryInfo = async (
  operatorAddress: Address, // generally masterSafeAddress
  serviceId: number,
): Promise<{
  bondValue: number;
  depositValue: number;
  serviceState: ServiceRegistryL2ServiceState;
}> => {
  const contractCalls = [
    serviceRegistryTokenUtilityContract.getOperatorBalance(
      operatorAddress,
      serviceId,
    ),
    serviceRegistryTokenUtilityContract.mapServiceIdTokenDeposit(serviceId),
    serviceRegistryL2Contract.mapServices(serviceId),
  ];

  const [
    operatorBalanceResponse,
    serviceIdTokenDepositResponse,
    mapServicesResponse,
  ] = await OPTIMISM_MULTICALL_PROVIDER.all(contractCalls);

  const [bondValue, depositValue, serviceState] = [
    parseFloat(ethers.utils.formatUnits(operatorBalanceResponse, 18)),
    parseFloat(ethers.utils.formatUnits(serviceIdTokenDepositResponse[1], 18)),
    mapServicesResponse.state as ServiceRegistryL2ServiceState,
  ];

  return {
    bondValue,
    depositValue,
    serviceState,
  };
};

/**
 * @param serviceId
 * @returns StakingProgram | null (null when not staked)
 */
const getCurrentStakingProgramByServiceId = async (
  serviceId: number,
  chainId: keyof typeof STAKING_PROGRAM_CONFIGS,
): Promise<StakingProgramId | null> => {
  if (serviceId <= -1) return null;

  const stakingTokenProxiesForChain =
    CONTRACT_CONFIG[chainId].STAKING_TOKEN_PROXYS;

  const contractCalls = Object.entries(stakingTokenProxiesForChain).reduce(
    (acc, [stakingProgramId, { address, abi }]) => ({
      ...acc,
      [stakingProgramId as StakingProgramId]: new MulticallContract(
        address,
        abi,
      ).getStakingState(serviceId),
    }),
    {},
  );

  try {
    const [
      isOptimusAlphaStaked,
      // isAlphaStaked,
      // isBetaStaked,
      // isBeta2Staked,
      // isBetaMechMarketplaceStaked,
    ] = await OPTIMISM_MULTICALL_PROVIDER.all(Object.values(contractCalls));

    if (isOptimusAlphaStaked) {
      return StakingProgramId.OptimusAlpha;
    }

    // if (isAlphaStaked) {
    //   return StakingProgramId.Alpha;
    // }

    // if (isBetaStaked) {
    //   return StakingProgramId.Beta;
    // }

    // if (isBeta2Staked) {
    //   return StakingProgramId.Beta2;
    // }

    // if (isBetaMechMarketplaceStaked) {
    //   return StakingProgramId.BetaMechMarketplace;
    // }

    return null;
  } catch (error) {
    console.error('Error while getting current staking program', error);
    return null;
  }
};

export const AutonolasService = {
  getAgentStakingRewardsInfo,
  getAvailableRewardsForEpoch,
  getCurrentStakingProgramByServiceId,
  getServiceRegistryInfo,
  getStakingContractInfoByServiceIdStakingProgram,
  getStakingContractInfoByStakingProgram,
};
